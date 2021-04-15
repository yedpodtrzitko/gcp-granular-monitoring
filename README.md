# GCP Granular Monitoring

## Motivation

GCP Cloud Monitoring can define Custom Metrics, however they have some limitations - you can't send data in interval shorter than one minute. Considering that AppEngine Standard can't run any 3rd party APM agents like DataDog etc., then you're out of luck with collecting frequent data.


## What is this?

A tiny library for gathering frequent monitoring data in Memorystore (Redis), and sending the interval's accumulated value into Cloud Monitoring.

Note: this code is ripped out of an older project as-is, so it contains hardcoded imports, which needs to be adjusted.


## Example
```
# send value for metric which should be accumulated as sum of all values. 
mark_point("summed_metric", 5, result="SUM")
mark_point("summed_metric", 10, result="SUM")

# send 
mark_point("averaged_metric", 20, result="AVG")
mark_point("averaged_metric", 40, result="AVG")

# send all gathered custom metrics for finished intervals (ie. the previous minute)
send_metrics()

# created metrics
# custom.googleapis.com/summed_metric_SUM - 15
# custom.googleapis.com/averaged_metric_AVG - 30
# custom.googleapis.com/averaged_metric_COUNT - 2
```
