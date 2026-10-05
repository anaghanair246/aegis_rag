# Evaluation results (auto-generated, measured)

Ingestion: {'total_seconds': 8.191, 'ingest_seconds': 8.178, 'knowledge_seconds': 0.008, 'documents': 17, 'passages': 102}


## retrieval_dev

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.2 | 0.706 | 0.824 | 0.536 | 0.549 | 0.85 | 17 |
| tfidf | 0.224 | 0.765 | 0.882 | 0.595 | 0.604 | 0.82 | 17 |
| hybrid | 0.212 | 0.735 | 0.882 | 0.535 | 0.554 | 0.83 | 17 |
| hybrid+alias | 0.212 | 0.725 | 0.882 | 0.533 | 0.549 | 1.04 | 17 |
| hybrid+alias+rerank+dedupe (default) | 0.247 | 0.814 | 0.941 | 0.634 | 0.643 | 2.47 | 17 |

## retrieval_para

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.143 | 0.643 | 0.643 | 0.449 | 0.496 | 1.05 | 14 |
| tfidf | 0.129 | 0.571 | 0.571 | 0.44 | 0.468 | 0.92 | 14 |
| hybrid | 0.129 | 0.571 | 0.571 | 0.467 | 0.492 | 0.81 | 14 |
| hybrid+alias | 0.114 | 0.5 | 0.5 | 0.407 | 0.421 | 1.43 | 14 |
| hybrid+alias+rerank+dedupe (default) | 0.129 | 0.607 | 0.643 | 0.439 | 0.471 | 2.83 | 14 |

## retrieval_held

| config | P@5 | R@5 | Hit@5 | MRR | nDCG@5 | retrieval_ms_mean | n_questions |
|---|---|---|---|---|---|---|---|
| bm25 | 0.157 | 0.614 | 0.643 | 0.393 | 0.437 | 0.95 | 14 |
| tfidf | 0.129 | 0.471 | 0.5 | 0.3 | 0.329 | 0.84 | 14 |
| hybrid | 0.171 | 0.686 | 0.714 | 0.344 | 0.416 | 0.82 | 14 |
| hybrid+alias | 0.157 | 0.614 | 0.643 | 0.338 | 0.394 | 1.44 | 14 |
| hybrid+alias+rerank+dedupe (default) | 0.143 | 0.543 | 0.571 | 0.327 | 0.37 | 3.66 | 14 |

## answers_dev

- n: **23**
- end_to_end_correct: **1.0**
- status_accuracy: **1.0**
- key_fact_recall(answerable): **1.0**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.622**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **1.0**
- false_abstentions(answerable): **0**
- latency_total_ms_p50: **6.5**
- latency_total_ms_max: **14.6**
- latency_retrieval_ms_mean: **4.1**

## answers_para

- n: **18**
- end_to_end_correct: **0.889**
- status_accuracy: **0.889**
- key_fact_recall(answerable): **0.929**
- citation_required_doc_recall: **1.0**
- citation_doc_precision: **0.499**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.0**
- abstention_recall(unanswerable): **0.75**
- abstention_precision: **0.75**
- false_abstentions(answerable): **1**
- latency_total_ms_p50: **5.8**
- latency_total_ms_max: **9.0**
- latency_retrieval_ms_mean: **4.2**

## answers_held

- n: **15**
- end_to_end_correct: **0.4**
- status_accuracy: **0.533**
- key_fact_recall(answerable): **0.786**
- citation_required_doc_recall: **0.786**
- citation_doc_precision: **0.589**
- unsupported_claim_rate: **0.0**
- hallucination_rate: **0.133**
- abstention_recall(unanswerable): **1.0**
- abstention_precision: **0.25**
- false_abstentions(answerable): **3**
- latency_total_ms_p50: **5.1**
- latency_total_ms_max: **6.3**
- latency_retrieval_ms_mean: **3.9**

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
| Q13 | dev | INSUFF | INSUFFICI | True | True | screenshot | [] |
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
| P12 | para | INSUFF | ANSWERED_ | True | False | fact_lookup | [] |
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
| H8 | held | ANSWER/ANSWER | ANSWERED_ | True | False | fact_lookup | ['150 bar', '220 bar'] |
| H9 | held | ANSWER/ANSWER | ANSWERED_ | True | True | fact_lookup | [] |
| H10 | held | ANSWER | ANSWERED_ | True | False | fact_lookup | ['10 s'] |
| H11 | held | INSUFF | INSUFFICI | True | True | fallback | [] |
| H12 | held | ANSWER/ANSWER | INSUFFICI | False | False | fallback | [] |
| H13 | held | ANSWER/ANSWER | ANSWERED_ | True | True | reset | [] |
| H14 | held | ANSWER | ANSWERED | True | True | location | [] |
| H15 | held | ANSWER | INSUFFICI | False | False | fallback | [] |