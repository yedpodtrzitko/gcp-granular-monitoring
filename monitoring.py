import logging
import time
from typing import List, Literal, Optional

from google.api_core.exceptions import InvalidArgument
from google.cloud import monitoring_v3

from application import settings
from sharedlib.enums import Monitoring
from sharedlib.redis import redis_client


def get_client() -> monitoring_v3.MetricServiceClient:
    return monitoring_v3.MetricServiceClient()


def list_time_series(metric: str):
    """No real usage, just for some testing while development."""
    interval = monitoring_v3.types.TimeInterval()
    now = time.time()
    interval.end_time.seconds = int(now)
    interval.start_time.seconds = int(now - 1200)

    results = monitor_client.list_time_series(
        project_path,
        f'metric.type = "custom.googleapis.com/{metric}"',
        interval,
        monitoring_v3.enums.ListTimeSeriesRequest.TimeSeriesView.FULL,
    )
    for result in results:
        print(result)


def recreate_metrics():
    """Create custom metrics.
    TODO - define as a fixture somewhere
    """
    all = monitor_client.list_metric_descriptors(
        project_path, filter_='metric.type=starts_with("custom.")'
    )
    for a in all:
        if "accumulator" in str(a) or "biquery" in str(a):
            metric_name = monitor_client.metric_descriptor_path(
                settings.PROJECT_ID, a.type
            )

            try:
                monitor_client.delete_metric_descriptor(metric_name)
            except Exception as e:
                print(e)

    metric_descriptor = {
        "type": f"custom.googleapis.com/{Monitoring.PING}",
        "labels": [
            {
                "key": "operation",
                "valueType": "STRING",
                # "description": "Performed operation name"
            }
        ],
        "metricKind": "GAUGE",
        "valueType": "DOUBLE",
        "unit": "items",
        "description": "Function performed in a loop with hard limit",
        "displayName": "Repeated Function Execution",
    }

    return monitor_client.create_metric_descriptor(
        settings.PROJECT_ID, metric_descriptor
    )


def mark_point(
    metric: str,
    value: float,
    result: Literal["SUM", "AVG"] = "SUM",
    timestamp: Optional[float] = None,
):
    """Save monitoring values into Redis.

    Custom metrics can take only one datapoint per minute, so we have to accumulate them
    and send all at once.

    - use the current minute timestamp as a marker for the key
    - append values as a string
    - expire in two minutes as a cleanup in case it wouldn't be collected

    # TODO - solve labels
    for label, label_value in labels.items():
        series.resource.labels[label] = label_value

    """
    now = int(time.time())
    current_minute_tstamp = timestamp or (now - (now % 60))
    key_name = f"{Monitoring.ACC_PREFIX}_{current_minute_tstamp}_{metric}"
    prefix = [
        metric,
        result,
        "FLOAT" if isinstance(value, float) else "INT",
    ]

    # create key and set expiry
    redis_client.set(key_name, "|".join(prefix), ex=120, nx=True)
    redis_client.append(key_name, f"|{value}")


def send_metrics(timestamp: Optional[float] = None) -> bool:
    """Send all accumulated metric values into Monitoring.

    Runs via cron every minute.
    """

    def new_point(metric_name: str, result: float):
        series = monitoring_v3.types.TimeSeries()
        series.metric.type = f"custom.googleapis.com/{metric_name}"

        point = series.points.add()
        point.interval.end_time.seconds = now

        if isinstance(result, float):
            point.value.double_value = result
        else:
            point.value.int64_value = result
        return series

    now = int(time.time())
    prev_minute_tstamp = timestamp or (now - (now % 60) - 60)
    metrics_pattern = f"{Monitoring.ACC_PREFIX}_{prev_minute_tstamp}_*"
    monitoring_keys = redis_client.keys(metrics_pattern)
    all_series = []
    for metric_key in monitoring_keys:
        raw_value = redis_client.get(metric_key)
        values: List[str] = raw_value.split("|")  # type: ignore
        metric_name = values.pop(0)  # metric name
        op = values.pop(0)  # operation - SUM or AVG
        typ = values.pop(0)  # INT or FLOAT
        if typ == "INT":
            result = sum(map(int, values))
            if op == "AVG":
                result = result // len(values)
        else:
            result = sum(map(float, values))  # type: ignore
            if op == "AVG":
                result = result / len(values)  # type: ignore

        all_series.append(new_point(metric_name, result))
        if op == "AVG":  # create count for AVG metric too
            all_series.append(new_point(f"{metric_name}_COUNT", len(values)))

    try:
        monitor_client.create_time_series(project_path, all_series)
    except InvalidArgument:
        logging.exception("mark_point failed")
        return False
    else:
        return True


monitor_client = get_client()
project_path = monitor_client.project_path(settings.PROJECT_ID)
