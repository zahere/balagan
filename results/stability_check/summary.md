# Balagan resilience summary

| Topology | none | crash | byzantine |
|---|---|---|---|
| flat | 96% (n=25) | 96% (n=25) | 100% (n=25) |
| hierarchical | 100% (n=25) | 76% (n=25) | 88% (n=25) |
| ring | 96% (n=25) | 92% (n=25) | 88% (n=25) |

- Trials: 225 | trial-level errors: 0
- LLM calls: 1400 | total tokens: 339824

Accuracy = share of trials where the mesh's collective decision matched ground truth. An undecided mesh scores as incorrect.
