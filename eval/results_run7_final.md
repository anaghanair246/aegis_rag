# Evaluation results (auto-generated, measured)

Ingestion: {'total_seconds': 13.542, 'ingest_seconds': 13.525, 'knowledge_seconds': 0.011, 'documents': 20, 'passages': 105}


## retrieval_dev

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.211 | 0.722 | 0.833 | 0.534 | 0.555 | 1.23 | 18 |
| tfidf | 0.233 | 0.778 | 0.889 | 0.618 | 0.612 | 1.22 | 18 |
| hybrid | 0.222 | 0.75 | 0.889 | 0.564 | 0.576 | 0.89 | 18 |
| hybrid+alias | 0.222 | 0.741 | 0.889 | 0.562 | 0.569 | 0.99 | 18 |
| hybrid+alias+rerank+dedupe (default) | 0.256 | 0.824 | 0.944 | 0.655 | 0.658 | 2.42 | 18 |

## retrieval_para

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.129 | 0.571 | 0.571 | 0.411 | 0.456 | 0.75 | 14 |
| tfidf | 0.129 | 0.571 | 0.571 | 0.44 | 0.468 | 1.06 | 14 |
| hybrid | 0.114 | 0.5 | 0.5 | 0.452 | 0.459 | 0.79 | 14 |
| hybrid+alias | 0.114 | 0.5 | 0.5 | 0.371 | 0.403 | 1.16 | 14 |
| hybrid+alias+rerank+dedupe (default) | 0.129 | 0.607 | 0.643 | 0.443 | 0.474 | 2.5 | 14 |

## retrieval_held

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.157 | 0.614 | 0.643 | 0.369 | 0.418 | 0.72 | 14 |
| tfidf | 0.129 | 0.471 | 0.5 | 0.306 | 0.334 | 0.84 | 14 |
| hybrid | 0.157 | 0.614 | 0.643 | 0.324 | 0.384 | 0.83 | 14 |
| hybrid+alias | 0.129 | 0.471 | 0.5 | 0.292 | 0.325 | 0.94 | 14 |
| hybrid+alias+rerank+dedupe (default) | 0.143 | 0.543 | 0.571 | 0.296 | 0.344 | 2.24 | 14 |

## retrieval_scr

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.28 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 5 |
| tfidf | 0.28 | 1.0 | 1.0 | 0.9 | 0.91 | 0.93 | 5 |
| hybrid | 0.28 | 1.0 | 1.0 | 1.0 | 1.0 | 0.91 | 5 |
| hybrid+alias | 0.28 | 1.0 | 1.0 | 1.0 | 0.975 | 1.02 | 5 |
| hybrid+alias+rerank+dedupe (default) | 0.28 | 1.0 | 1.0 | 0.8 | 0.849 | 2.49 | 5 |

## answers_dev

- n: **23**
- end_to_end_correct: **1.0**
- status_accuracy: **1.0**
- key_fact_recall(answerable): **1.0**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.615**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **1.0**
- false_abstentions(answerable): **0**
- latency_total_ms_p50: **6.6**
- latency_total_ms_max: **14.7**
- latency_retrieval_ms_mean: **4.3**

## answers_para

- n: **18**
- end_to_end_correct: **0.944**
- status_accuracy: **0.944**
- key_fact_recall(answerable): **0.929**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.499**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **0.8**
- false_abstentions(answerable): **1**
- latency_total_ms_p50: **5.8**
- latency_total_ms_max: **8.5**
- latency_retrieval_ms_mean: **4.1**

## answers_held

- n: **15**
- end_to_end_correct: **0.467**
- status_accuracy: **0.533**
- key_fact_recall(answerable): **0.786**
- citation_required_doc_recall: **0.786**
- citation_doc_precision: **0.589**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **0.25**
- false_abstentions(answerable): **3**
- latency_total_ms_p50: **6.5**
- latency_total_ms_max: **9.6**
- latency_retrieval_ms_mean: **4.9**

## answers_scr

- n: **6**
- end_to_end_correct: **1.0**
- status_accuracy: **1.0**
- key_fact_recall(answerable): **1.0**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.367**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **1.0**
- false_abstentions(answerable): **0**
- latency_total_ms_p50: **12.8**
- latency_total_ms_max: **17.8**
- latency_retrieval_ms_mean: **6.2**

## Per-question

| id | set | expected | got | facts | correct | handler | ungrounded nums |
|---|---|---|---|---|---|---|---|
| Q1 | dev | ANSWER | ANSWERED | True | True | startup | [] |
| Q2 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | normal_pressure | [] |
| Q3 | dev | ANSWER | ANSWERED | True | True | alarm_meaning | [] |
| Q4 | dev | ANSWER | ANSWERED | True | True | identity | [] |
| Q5 | dev | ANSWER | ANSWERED | True | True | introduced_by | [] |
| Q6 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | schematic_links | [] |
| Q7 | dev | ANSWER | ANSWERED | True | True | a17_persist | [] |
| Q8 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | reset | [] |
| Q9 | dev | ANSWER | ANSWERED | True | True | pressure_history | [] |
| Q10 | dev | ANSWER | ANSWERED | True | True | alarm_for_reading | [] |
| Q11 | dev | ANSWER | ANSWERED | True | True | location | [] |
| Q12 | dev | ANSWER | ANSWERED | True | True | slide_novelty | [] |
| Q13 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | screenshot | [] |
| Q14 | dev | ANSWER | ANSWERED | True | True | revision_history | [] |
| Q15 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | config_key | [] |
| Q16 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | pressure_scope | [] |
| Q17 | dev | ANSWER | ANSWERED | True | True | identity | [] |
| Q18 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | pressure_history | [] |
| Q19 | dev | INSUFF | INSUFFICI | True | True | gap | [] |
| Q20 | dev | INSUFF | INSUFFICI | True | True | gap | [] |
| Q21 | dev | INSUFF | INSUFFICI | True | True | gap | [] |
| Q22 | dev | INSUFF | INSUFFICI | True | True | gap | [] |
| Q23 | dev | INSUFF | INSUFFICI | True | True | gap | [] |
| P1 | para | ANSWER | ANSWERED | True | True | startup | [] |
| P2 | para | ANSWER/ANSWER | ANSWERED_ | True | True | normal_pressure | [] |
| P3 | para | ANSWER | ANSWERED | True | True | alarm_meaning | [] |
| P4 | para | ANSWER | ANSWERED | True | True | identity | [] |
| P5 | para | ANSWER | ANSWERED | True | True | introduced_by | [] |
| P6 | para | ANSWER | ANSWERED | True | True | a17_persist | [] |
| P7 | para | ANSWER/ANSWER | ANSWERED_ | True | True | reset | [] |
| P8 | para | ANSWER | ANSWERED | True | True | location | [] |
| P9 | para | ANSWER | ANSWERED | True | True | alarm_for_reading | [] |
| P10 | para | ANSWER | ANSWERED | True | True | revision_history | [] |
| P11 | para | INSUFF | INSUFFICI | True | True | fallback | [] |
| P12 | para | INSUFF | INSUFFICI | True | True | gap | [] |
| P13 | para | ANSWER | INSUFFICI | False | False | fallback | [] |
| P14 | para | ANSWER/ANSWER | ANSWERED_ | True | True | normal_pressure | [] |
| P15 | para | ANSWER/ANSWER | ANSWERED_ | True | True | reset | [] |
| P16 | para | INSUFF | INSUFFICI | True | True | fallback | [] |
| P17 | para | ANSWER/ANSWER | ANSWERED_ | True | True | term | [] |
| P18 | para | INSUFF | INSUFFICI | True | True | entity_guard | [] |
| H1 | held | ANSWER | ANSWERED_ | True | False | fact_lookup | [] |
| H2 | held | ANSWER/ANSWER | ANSWERED_ | True | True | normal_pressure | [] |
| H3 | held | ANSWER | ANSWERED_ | True | False | fact_lookup | [] |
| H4 | held | ANSWER/ANSWER | ANSWERED_ | True | True | extractive | [] |
| H5 | held | ANSWER/ANSWER | ANSWERED_ | False | False | extractive | [] |
| H6 | held | ANSWER/ANSWER | INSUFFICI | True | False | fallback | [] |
| H7 | held | ANSWER | ANSWERED_ | True | False | fact_lookup | [] |
| H8 | held | ANSWER/ANSWER | ANSWERED_ | True | True | fact_lookup | [] |
| H9 | held | ANSWER/ANSWER | ANSWERED_ | True | True | fact_lookup | [] |
| H10 | held | ANSWER | ANSWERED_ | True | False | fact_lookup | [] |
| H11 | held | INSUFF | INSUFFICI | True | True | fallback | [] |
| H12 | held | ANSWER/ANSWER | INSUFFICI | False | False | fallback | [] |
| H13 | held | ANSWER/ANSWER | ANSWERED_ | True | True | reset | [] |
| H14 | held | ANSWER | ANSWERED | True | True | location | [] |
| H15 | held | ANSWER | INSUFFICI | False | False | fallback | [] |
| S1 | scr | ANSWER/ANSWER | ANSWERED_ | True | True | screenshot | [] |
| S2 | scr | ANSWER/ANSWER | ANSWERED_ | True | True | screenshot | [] |
| S3 | scr | ANSWER/ANSWER | ANSWERED_ | True | True | screenshot | [] |
| S4 | scr | ANSWER/ANSWER | ANSWERED_ | True | True | screenshot | [] |
| S5 | scr | ANSWER/ANSWER | ANSWERED_ | True | True | screenshot | [] |
| S6 | scr | INSUFF | INSUFFICI | True | True | gap | [] |