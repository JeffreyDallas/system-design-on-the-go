# Distributed API Rate Limiting — Engineering Preparation Notes

## Problem
Design a distributed API rate limiter across gateway instances in multiple regions.
Constraints still need discovery: desired consistency for paid-user quotas, burst
allowance for anonymous users, per-request latency budget, regional disaster recovery,
limits of the Redis cluster, and operational controls during a partial outage.

## Design alternatives
A shared Redis counter can coordinate decisions across gateway nodes. Atomic
operations are useful to avoid lost updates. However, each additional network
roundtrip affects latency, hot keys can produce skew, and failures force a product
policy decision about failing open versus failing closed.

A local token bucket with asynchronous quota reconciliation can reduce central
coordination. However, limits can be exceeded under concurrent traffic and failovers.
The tolerable overshoot depends on abuse risk and contracts.

## Reliability considerations
Measure P50/P95/P99 latency, rejection rates, replica disagreement, regional outage
recovery, allocation fairness, and peak-traffic hot-key distribution. Monitor the
shared backing service saturation and split emergency behavior by endpoint.

## Discussion guidance
The team should compare alternatives rather than declaring a universal solution.
Any numerical scale figures are hypotheses for an experimental load test, not
verified production benchmarks.
