# Effective-Layer-Pruning (ICPR-2024 Oral Presentation)

This repository provides code examples of our CKA criterion for layer pruning, including some of our pruned models. <br />

To observe and understand the functionality of our method, we simplify many training/fine-tuning parameters. If you are interested in reproducing our results, please follow the steps below: <br />
1 - Put debug=false <br />
2 - Increase the number of epochs in the fine-tuning function to 200. <br />
3 - Divide the learning rate by 10 at epochs 100 and 150. <br />
4 - Use data augmentation (details in the paper)

Please cite our paper in your publications if it helps your research.
```bash
@inproceedings{Pons:2024,
author    = {Ian Pons,
Bruno Yamamoto,
Anna H. Reali Costa and
Artur Jordao},
title     = {Effective Layer Pruning Through Similarity Metric Perspective},
booktitle = {International Conference on Pattern Recognition (ICPR).},
year = {2024},
}
```
