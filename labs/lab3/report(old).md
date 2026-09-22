(AI in Practice - 1) nataltiger@Ajays-MacBook-Air AI in Practice - 1 % python labs/lab3/search.py --baseline

corpus: 30 docs -> 91 chunks (mean 707 chars)
config                           hit_rate@1     hit_rate@5       recall@5            mrr        ndcg@10 latency_p95_ms
----------------------------------------------------------------------------------------------------------------------
baseline sliding-800 dense           0.7857         0.9286         0.8452         0.8451         0.8053       885.7558

kind             hit_rate@5     n
---------------------------------
aggregation          1.0000     4
multi_hop            1.0000    10
paraphrase           1.0000     5
single_hop           0.8889    18
trap_archived        1.0000     3
unanswerable         0.5000     2

Write these numbers down before you change anything.





(AI in Practice - 1) nataltiger@Ajays-MacBook-Air AI in Practice - 1 % python labs/lab3/search.py --sweep chunking


corpus: 30 docs -> 83 chunks (mean 665 chars)
config                hit_rate@1     hit_rate@5       recall@5            mrr        ndcg@10 latency_p95_ms
-----------------------------------------------------------------------------------------------------------
fixed 800 dense           0.7381         0.9524         0.8373         0.8387         0.7952         1.2920

kind             hit_rate@5     n
---------------------------------
aggregation          1.0000     4
multi_hop            1.0000    10
paraphrase           1.0000     5
single_hop           0.9444    18
trap_archived        1.0000     3
unanswerable         0.5000     2
Write these numbers down before you change anything.

corpus: 30 docs -> 91 chunks (mean 707 chars)
config                  hit_rate@1     hit_rate@5       recall@5            mrr        ndcg@10 latency_p95_ms
-------------------------------------------------------------------------------------------------------------
sliding 800 dense           0.7857         0.9286         0.8452         0.8451         0.8053         0.3055


kind             hit_rate@5     n
---------------------------------
aggregation          1.0000     4
multi_hop            1.0000    10
paraphrase           1.0000     5
single_hop           0.8889    18
trap_archived        1.0000     3
unanswerable         0.5000     2
Write these numbers down before you change anything.

corpus: 30 docs -> 98 chunks (mean 666 chars)
  embedded 98/98 (1994 ms/batch)
config                    hit_rate@1     hit_rate@5       recall@5            mrr        ndcg@10 latency_p95_ms
---------------------------------------------------------------------------------------------------------------
recursive 800 dense           0.7857         0.9286         0.8393         0.8552         0.8127         0.3484

kind             hit_rate@5     n
---------------------------------
aggregation          1.0000     4
multi_hop            1.0000    10
paraphrase           1.0000     5
single_hop           0.9444    18
trap_archived        1.0000     3
unanswerable         0.0000     2
Write these numbers down before you change anything.


corpus: 30 docs -> 164 chunks (mean 363 chars)
  embedded 164/164 (2031 ms/batch)
config                   hit_rate@1     hit_rate@5       recall@5            mrr        ndcg@10 latency_p95_ms
--------------------------------------------------------------------------------------------------------------
markdown 800 dense           0.7619         0.9762         0.8988         0.8720         0.8458         0.3390


kind             hit_rate@5     n
---------------------------------
aggregation          1.0000     4
multi_hop            1.0000    10
paraphrase           1.0000     5
single_hop           1.0000    18
trap_archived        1.0000     3
unanswerable         0.5000     2
Write these numbers down before you change anything.

(AI in Practice - 1) nataltiger@Ajays-MacBook-Air AI in Practice - 1 % 







