# CNN Training Best Practices

A practical reference for training Convolutional Neural Networks, with emphasis on
1D CNNs applied to financial time-series data.

---

## Table of Contents

1. [Data Preparation](#1-data-preparation)
2. [Architecture Design](#2-architecture-design)
3. [Training Hyperparameters](#3-training-hyperparameters)
4. [Regularization](#4-regularization)
5. [Overfitting vs Underfitting](#5-overfitting-vs-underfitting)
6. [Loss Functions and Metrics](#6-loss-functions-and-metrics)
7. [Transfer Learning vs From Scratch](#7-transfer-learning-vs-from-scratch)
8. [Evaluation and Validation](#8-evaluation-and-validation)
9. [1D CNNs for Time-Series / Financial Data](#9-1d-cnns-for-time-series--financial-data)
10. [Common Failure Modes](#10-common-failure-modes)
11. [Key Takeaways](#key-takeaways)
12. [Sources](#sources)

---

## 1. Data Preparation

### Normalization
- Scale inputs to `[0, 1]` (min-max) or z-score standardize (mean=0, std=1)
- Compute statistics on **training set only** — apply the same transform to val/test
- BatchNorm or LayerNorm inside the network complements input normalization
- Stable inputs → stable gradients → faster convergence

### Data Augmentation
- **Images**: rotation, flipping, cropping, noise injection, PCA jitter
- **Time-series**: time-warping, amplitude scaling, jittering, window slicing
- Aggressive augmentation is second only to real data as a regularizer
- Do **not** augment the validation or test sets

### Train / Validation / Test Splits
| Set | Typical share | Purpose |
|-----|--------------|---------|
| Train | 70–80% | Weight updates |
| Validation | 10–15% | Hyperparameter selection, early stopping |
| Test | 10–15% | Final unbiased evaluation |

- **For time-series**: use a chronological split — never shuffle across time
- Validation guides decisions; test set is touched exactly once

---

## 2. Architecture Design

### Depth and Filter Progression
- Increase filters after each pooling/stride: `32 → 64 → 128 → 256`
- Deeper ≠ always better; diminishing returns appear quickly
- Start with a known baseline (ResNet, VGG) before custom designs

### Kernel / Filter Size
- **3×3** (2D) or **3–5 timesteps** (1D) is the standard workhorse
- Larger kernels (7×7, 11) useful at the first layer to capture broad patterns
- Stack two 3×3 layers instead of one 5×5 — same receptive field, fewer params

### Pooling
- Max pooling: standard downsampling; preserves strongest activations
- Average pooling: smoother; useful at the final feature map before FC layers
- Modern trend: replace pooling with **strided convolutions** (keeps gradients flowing)

### Batch Normalization
- Insert **after** conv and **before** activation (ReLU)
- Normalizes per-channel activations within each mini-batch
- Benefits: faster convergence, allows higher LR, less sensitive to initialization
- Required for deep networks (10+ layers)

### Dropout
- Apply primarily to **fully connected layers** (20–50%)
- Can apply after conv blocks but is less critical there
- At inference: disabled; activations scaled by keep probability

### Gated Architectures (GLU)
- Gated Linear Unit: `output = conv_main(x) × sigmoid(conv_gate(x))`
- Gate learns to silence noisy channels without manual feature engineering
- Works well for heterogeneous financial indicators (some channels irrelevant)

---

## 3. Training Hyperparameters

### Learning Rate
| Scenario | Starting LR |
|----------|------------|
| From scratch | 1e-3 |
| Fine-tuning pre-trained | 1e-5 – 1e-4 |
| Too high (loss oscillates) | Halve it |
| Too low (loss barely moves) | Double it |

- Always use a **scheduler** — don't keep LR constant throughout training
- `ReduceLROnPlateau` (decay when val loss stalls) is the most practical choice

### Batch Size
- **16–32**: More gradient noise, better generalization, slower wall-clock
- **128–256**: Stable gradients, faster epochs, can hurt generalization
- Rule of thumb: start at 32; increase only if GPU is underutilized
- When increasing batch size, scale LR proportionally (`linear scaling rule`)

### Optimizers
| Optimizer | When to use |
|-----------|------------|
| **AdamW** | Default for most tasks; fast convergence; correct weight decay |
| **SGD + momentum (0.9)** | Often wins given enough epochs; better final generalization |
| **RMSProp** | Noisy/sparse gradients; works well for RNNs and some RL tasks |

### Learning Rate Schedulers
- `StepLR`: decay by factor every N epochs
- `CosineAnnealingLR`: smooth decay to near-zero; good for ensembling
- `ReduceLROnPlateau`: most practical — reacts to actual validation behavior
- **Warmup**: linear ramp for first 5–10 epochs prevents early divergence

### Number of Epochs
- Train until validation loss stops improving (use early stopping)
- Don't set a fixed epoch count — it's dataset-dependent
- Typical range: 50–200 epochs for medium datasets

---

## 4. Regularization

### L2 / Weight Decay
- Penalizes large weights: `loss += λ·Σw²`
- Typical `λ`: 1e-4 to 1e-2
- Use `AdamW` (not `Adam`) for correct weight decay with adaptive optimizers

### L1 Regularization
- `loss += λ·Σ|w|` — promotes sparsity; useful as implicit feature selection
- Less common than L2 in practice

### Dropout
- Randomly zeros neurons during training; forces redundant representations
- Rate 0.2–0.5; start at 0.3 and tune

### Early Stopping
- Monitor val loss; stop when it hasn't improved for `patience` epochs (e.g., 10–20)
- Save best checkpoint during training; restore it at the end
- Mathematically equivalent to L2 regularization in some settings

### BatchNorm as Regularizer
- Adds slight noise via mini-batch statistics; can reduce need for dropout
- Do not use BatchNorm and heavy dropout simultaneously without testing

---

## 5. Overfitting vs Underfitting

### Diagnosing
```
Plot training loss vs validation loss over epochs:

     Loss
      |  val loss ↑           ← OVERFITTING
      | train loss ↓
      |___________________________ epochs

      |  both stay high       ← UNDERFITTING
      |
      |___________________________ epochs

      |  both converge low    ← GOOD FIT
      |
      |___________________________ epochs
```

### Overfitting Fixes (in priority order)
1. More real training data
2. Stronger data augmentation
3. Add / increase dropout
4. Increase weight decay
5. Reduce model capacity
6. Early stopping

### Underfitting Fixes
1. Increase model depth or width
2. Train for more epochs
3. Raise learning rate (slightly)
4. Reduce regularization
5. Improve feature quality

---

## 6. Loss Functions and Metrics

### Classification
| Loss | When to use |
|------|------------|
| `CrossEntropyLoss` | Multi-class; standard default |
| `BCEWithLogitsLoss` | Binary classification |
| `FocalLoss` | Imbalanced classes; focuses on hard examples |

### Regression
| Loss | When to use |
|------|------------|
| `MSELoss` | Standard; penalizes large errors heavily |
| `MAELoss` (L1) | Robust to outliers |
| `HuberLoss` | Hybrid MSE/MAE; best of both worlds |

### Evaluation Metrics
- **Balanced accuracy / F1**: Use for imbalanced labels (not plain accuracy)
- **AUC-ROC**: Threshold-independent; excellent for binary problems
- **Confusion matrix**: Mandatory; reveals per-class failures
- **Walk-forward efficiency (WFE)**: For time-series; measures OOS generalization

### Class Imbalance
- Pass `weight` param to `CrossEntropyLoss` (inverse class frequency)
- Or: oversample minority class (SMOTE for tabular; time-warping for series)
- Avoid reporting plain accuracy on imbalanced data — it hides failures

---

## 7. Transfer Learning vs From Scratch

### Use Transfer Learning When
- Dataset < ~50K samples
- Domain is similar to source (e.g., natural images → ImageNet)
- Limited compute budget
- This covers the majority of practical use cases

### Train From Scratch When
- Very large, domain-specific dataset
- Task fundamentally different from available pre-trained models
- 1D financial time-series (no good public pre-trained backbone exists — train from scratch)

### Fine-Tuning Strategy
```
Phase 1: Freeze all pre-trained layers → train only the new head (3–5 epochs)
Phase 2: Unfreeze last N blocks → fine-tune with LR 10–100× smaller than scratch
Phase 3 (optional): Unfreeze all → very small LR, short training
```

---

## 8. Evaluation and Validation

### K-Fold Cross-Validation
- Split data into k folds; train on k-1, evaluate on held-out fold
- Repeat k times; average all metrics
- `k=5` or `k=10` typical; `k=3` for large datasets
- Use **stratified** folds for imbalanced class distributions

### Walk-Forward Validation (Time-Series)
```
Fold 1:  [train ████████] [val ██]
Fold 2:  [train ██████████] [val ██]
Fold 3:  [train ████████████] [val ██]
```
- Always train on the past, validate on the future
- Never shuffle time-series data across folds — creates data leakage
- Simulate real deployment: model only sees data available at prediction time

### Walk-Forward Efficiency (WFE)
- OOS R² between predicted and actual on validation fold
- `WFE ≥ 0.70`: HEALTHY — model generalizes well
- `0.50 ≤ WFE < 0.70`: DEGRADED — monitor closely
- `WFE < 0.50`: POOR — retrain or increase training window

---

## 9. 1D CNNs for Time-Series / Financial Data

### Input Shape
```python
# Input: [batch_size, n_channels, sequence_length]
# n_channels = number of input features (indicators, sources)
# sequence_length = lookback window (e.g., 30 bars)
x = torch.randn(32, 10, 30)  # 32 samples, 10 features, 30-bar window
```

### Architecture Differences vs 2D CNNs
| Property | 2D (images) | 1D (time-series) |
|----------|------------|-----------------|
| Kernel | 3×3 spatial | 3–7 temporal |
| Pooling | Preserves width/height | Reduces sequence length |
| Symmetry | Spatial symmetry | Temporal asymmetry (past ≠ future) |
| Transfer learning | Very effective (ImageNet) | Rarely effective — train from scratch |
| Augmentation | Rotation, flip, crop | Jitter, scale, time-warp |

### Filter Sizes for Financial Data
- `kernel_size=3`: Captures 3-bar local patterns (short-term momentum)
- `kernel_size=5–7`: Medium-term regime structure
- Stack layers to grow receptive field: two `k=3` layers → 5-bar effective field

### Financial Feature Engineering
- **Normalize per-feature**: z-score each channel independently on training window
- **Stationarity**: Use log-returns (`ln(p_t / p_{t-1})`) not raw prices
- **No lookahead**: Features must only use data available at bar `t`
- **Useful channels**: price return, volume, RSI, MACD, ATR, realized volatility, BTC correlation, funding rate, time-of-day (sin/cos encoding)

### Training Notes for Financial CNNs
- Use **chronological split** — never shuffle across time
- Expect noisier gradients than image tasks; use smaller LR and more epochs
- Dropout 0.3–0.5 critical — financial signals are weak and noisy
- Monitor WFE on held-out period, not just training loss
- Retrain periodically as market regime changes (concept drift)

### Gated Conv (GLU) for Heterogeneous Indicators
```python
class GatedConv1d(nn.Module):
    def __init__(self, in_ch, out_ch, kernel_size):
        super().__init__()
        self.conv_main = nn.Conv1d(in_ch, out_ch, kernel_size, padding=kernel_size//2)
        self.conv_gate = nn.Conv1d(in_ch, out_ch, kernel_size, padding=kernel_size//2)

    def forward(self, x):
        return self.conv_main(x) * torch.sigmoid(self.conv_gate(x))
```
- Gate learns to suppress irrelevant or noisy indicator channels
- Avoids manual feature selection; model learns what to trust

---

## 10. Common Failure Modes

### Training Loss is NaN
- Cause: LR too high, exploding gradients, bad BatchNorm
- Fix: Halve LR; add `torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)`; check for NaN in input data

### Loss Not Decreasing
- Cause: LR too low, wrong optimizer, model too shallow, bad initialization
- Fix: Raise LR; switch to AdamW; verify data pipeline is correct

### Good Training Loss, Bad Validation Loss
- Cause: Overfitting
- Fix: Dropout, weight decay, more data, early stopping

### Model Predicts One Class Only
- Cause: Class imbalance; model learned majority-class shortcut
- Fix: Class weights in loss function; stratified batches; check label distribution

### Slow Convergence on Financial Data
- Cause: Weak signal-to-noise ratio; non-stationary inputs
- Fix: Use log-returns (not raw prices); z-score each channel; reduce LR

### Karpathy's Debugging Recipe
1. **Inspect raw data** — scan hundreds of samples; understand distribution
2. **Overfit a single batch** — loss should reach ~0; if not, model or pipeline is broken
3. **Add regularization one piece at a time** — dropout, then weight decay, then augmentation
4. **Plot everything** — loss curves, gradient norms, activation distributions
5. **Start simple** — a 2-layer 1D CNN that works beats a 10-layer one that doesn't

---

## Key Takeaways

1. **Data quality beats model complexity** — clean, well-normalized data is the highest leverage action
2. **Always use a validation set** — never tune on the test set
3. **Start simple** — overfit a tiny model first; prove the pipeline works
4. **Regularize by default** — dropout + weight decay + early stopping from day one
5. **Match loss to task** — classification → cross-entropy, regression → MSE/Huber, imbalanced → focal
6. **Time-series is different** — chronological splits, no shuffle, log-returns, expect noisy gradients
7. **Monitor WFE** — training loss alone hides generalization failure on time-series
8. **Retrain periodically** — financial models degrade as market regime shifts
9. **GLU gates beat dropout alone** — for heterogeneous indicator channels
10. **Visualize everything** — gradient norms, loss curves, confusion matrices

---

## Sources

- [A Recipe for Training Neural Networks — Andrej Karpathy](http://karpathy.github.io/2019/04/25/recipe/)
- [CS231n Convolutional Neural Networks](https://cs231n.github.io/convolutional-networks/)
- [CS231n Transfer Learning](https://cs231n.github.io/transfer-learning/)
- [How to Develop CNN Models for Time Series Forecasting — Machine Learning Mastery](https://machinelearningmastery.com/how-to-develop-convolutional-neural-network-models-for-time-series-forecasting/)
- [Using CNN for Financial Time Series Prediction — Machine Learning Mastery](https://machinelearningmastery.com/using-cnn-for-financial-time-series-prediction/)
- [Avoiding Overfitting: A Survey on Regularization Methods for CNNs — ACM](https://dl.acm.org/doi/full/10.1145/3510413)
- [Dropout: A Simple Way to Prevent Neural Networks from Overfitting — Hinton et al.](https://www.cs.toronto.edu/~hinton/absps/JMLRdropout.pdf)
- [Weight Decay vs L2 Regularization — Towards Data Science](https://towardsdatascience.com/weight-decay-l2-regularization-90a9e17713cd/)
- [A Gentle Introduction to k-fold Cross-Validation — Machine Learning Mastery](https://machinelearningmastery.com/k-fold-cross-validation/)
- [1D CNNs for Chart Pattern Classification in Financial Time Series — Springer](https://link.springer.com/article/10.1007/s11227-022-04431-5)
- [The Ultimate Guide to Deep Learning Hyperparameter Tuning — Training Data](https://www.blog.trainindata.com/the-ultimate-guide-to-deep-learning-hyperparameter-tuning/)
- [PyTorch Documentation](https://pytorch.org/docs/stable/index.html)
