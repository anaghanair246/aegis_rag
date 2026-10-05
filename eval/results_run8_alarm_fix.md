# Evaluation results (auto-generated, measured)

Ingestion: {'total_seconds': 17.214, 'ingest_seconds': 17.19, 'knowledge_seconds': 0.013, 'documents': 20, 'passages': 105}


## retrieval_dev

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.211 | 0.722 | 0.833 | 0.534 | 0.555 | 1.23 | 18 |
| tfidf | 0.233 | 0.778 | 0.889 | 0.618 | 0.612 | 1.0 | 18 |
| hybrid | 0.222 | 0.75 | 0.889 | 0.564 | 0.576 | 1.02 | 18 |
| hybrid+alias | 0.222 | 0.741 | 0.889 | 0.562 | 0.569 | 1.26 | 18 |
| hybrid+alias+rerank+dedupe (default) | 0.256 | 0.824 | 0.944 | 0.655 | 0.658 | 2.99 | 18 |

## retrieval_para

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.129 | 0.571 | 0.571 | 0.411 | 0.456 | 2.2 | 14 |
| tfidf | 0.129 | 0.571 | 0.571 | 0.44 | 0.468 | 2.54 | 14 |
| hybrid | 0.114 | 0.5 | 0.5 | 0.452 | 0.459 | 1.48 | 14 |
| hybrid+alias | 0.114 | 0.5 | 0.5 | 0.371 | 0.403 | 1.3 | 14 |
| hybrid+alias+rerank+dedupe (default) | 0.129 | 0.607 | 0.643 | 0.443 | 0.474 | 2.94 | 14 |

## retrieval_held

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.157 | 0.614 | 0.643 | 0.369 | 0.418 | 0.96 | 14 |
| tfidf | 0.129 | 0.471 | 0.5 | 0.306 | 0.334 | 0.93 | 14 |
| hybrid | 0.157 | 0.614 | 0.643 | 0.324 | 0.384 | 0.95 | 14 |
| hybrid+alias | 0.129 | 0.471 | 0.5 | 0.292 | 0.325 | 1.2 | 14 |
| hybrid+alias+rerank+dedupe (default) | 0.143 | 0.543 | 0.571 | 0.296 | 0.344 | 2.8 | 14 |

## retrieval_scr

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.28 | 1.0 | 1.0 | 1.0 | 1.0 | 1.11 | 5 |
| tfidf | 0.28 | 1.0 | 1.0 | 0.9 | 0.91 | 1.05 | 5 |
| hybrid | 0.28 | 1.0 | 1.0 | 1.0 | 1.0 | 1.09 | 5 |
| hybrid+alias | 0.28 | 1.0 | 1.0 | 1.0 | 0.975 | 1.43 | 5 |
| hybrid+alias+rerank+dedupe (default) | 0.28 | 1.0 | 1.0 | 0.8 | 0.849 | 3.21 | 5 |

## retrieval_alarm

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.2 | 1.0 | 1.0 | 0.786 | 0.842 | 0.98 | 7 |
| tfidf | 0.2 | 1.0 | 1.0 | 1.0 | 1.0 | 0.93 | 7 |
| hybrid | 0.2 | 1.0 | 1.0 | 0.786 | 0.842 | 0.93 | 7 |
| hybrid+alias | 0.2 | 1.0 | 1.0 | 0.786 | 0.842 | 1.13 | 7 |
| hybrid+alias+rerank+dedupe (default) | 0.2 | 1.0 | 1.0 | 0.786 | 0.842 | 2.84 | 7 |

## answers_dev

- n: **23**
- end_to_end_correct: **1.0**
- status_accuracy: **1.0**
- key_fact_recall(answerable): **1.0**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.606**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **1.0**
- false_abstentions(answerable): **0**
- latency_total_ms_p50: **10.2**
- latency_total_ms_max: **23.9**
- latency_retrieval_ms_mean: **5.8**

## answers_para

- n: **18**
- end_to_end_correct: **0.944**
- status_accuracy: **0.944**
- key_fact_recall(answerable): **0.929**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.487**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **0.8**
- false_abstentions(answerable): **1**
- latency_total_ms_p50: **9.2**
- latency_total_ms_max: **19.7**
- latency_retrieval_ms_mean: **5.2**

## answers_held

- n: **15**
- end_to_end_correct: **0.667**
- status_accuracy: **0.733**
- key_fact_recall(answerable): **0.786**
- citation_required_doc_recall: **0.857**
- citation_doc_precision: **0.625**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **0.25**
- false_abstentions(answerable): **3**
- latency_total_ms_p50: **9.5**
- latency_total_ms_max: **19.5**
- latency_retrieval_ms_mean: **5.3**

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
- latency_total_ms_p50: **10.7**
- latency_total_ms_max: **13.2**
- latency_retrieval_ms_mean: **5.4**

## answers_alarm

- n: **10**
- end_to_end_correct: **1.0**
- status_accuracy: **1.0**
- key_fact_recall(answerable): **1.0**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.786**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **1.0**
- false_abstentions(answerable): **0**
- latency_total_ms_p50: **11.8**
- latency_total_ms_max: **15.5**
- latency_retrieval_ms_mean: **4.7**

## Per-question

| id | set | expected | got | facts | correct | handler | ungrounded nums |
|---|---|---|---|---|---|---|---|
| Q1 | dev | ANSWER | ANSWERED | True | True | startup | [] |
| Q2 | dev | ANSWER/ANSWER | ANSWERED_ | True | True | normal_pressure | [] |
| Q3 | dev | ANSWER | ANSWERED | True | True | alarm_ref | [] |
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
| P3 | para | ANSWER | ANSWERED | True | True | alarm_ref | [] |
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
| H3 | held | ANSWER | ANSWERED | True | True | alarm_ref | [] |
| H4 | held | ANSWER/ANSWER | ANSWERED_ | True | True | extractive | [] |
| H5 | held | ANSWER/ANSWER | ANSWERED_ | False | False | extractive | [] |
| H6 | held | ANSWER/ANSWER | INSUFFICI | True | False | fallback | [] |
| H7 | held | ANSWER | ANSWERED | True | True | alarm_ref | [] |
| H8 | held | ANSWER/ANSWER | ANSWERED_ | True | True | fact_lookup | [] |
| H9 | held | ANSWER/ANSWER | ANSWERED_ | True | True | fact_lookup | [] |
| H10 | held | ANSWER | ANSWERED | True | True | alarm_ref | [] |
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
| AL1 | alarm | ANSWER/ANSWER | ANSWERED_ | True | True | alarm_ref | [] |
| AL2 | alarm | ANSWER/ANSWER | ANSWERED_ | True | True | alarm_ref | [] |
| AL3 | alarm | ANSWER | ANSWERED | True | True | alarm_ref | [] |
| AL4 | alarm | INSUFF | INSUFFICI | True | True | alarm_ref | [] |
| AL5 | alarm | ANSWER | ANSWERED | True | True | alarm_ref | [] |
| AL6 | alarm | ANSWER | ANSWERED | True | True | alarm_ref | [] |
| AL7 | alarm | INSUFF | INSUFFICI | True | True | alarm_ref | [] |
| AL8 | alarm | INSUFF | INSUFFICI | True | True | alarm_ref | [] |
| AL9 | alarm | ANSWER/ANSWER | ANSWERED | True | True | alarm_ref | [] |
| AL10 | alarm | ANSWER | ANSWERED | True | True | alarm_ref | [] |