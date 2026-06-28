"""
旧模倣学習モデル (ptcg_baseline_model.pth) を使うエージェントラッパー。
submission/main.py のロジックをそのまま使い、モデルだけ明示的に baseline に固定する。
"""
import os, sys, importlib.util
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

HERE       = os.path.dirname(os.path.abspath(__file__))
SUBMISSION = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'submission'))

# submission/main.py を独立したモジュールとして読み込む
_spec = importlib.util.spec_from_file_location('_sub_baseline', os.path.join(SUBMISSION, 'main.py'))
_sub  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sub)  # _load_model() が走り RL モデルを読む可能性あり

# 強制的に baseline モデルで上書き
class _Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(5658, 1024)
        self.ln1 = nn.LayerNorm(1024)
        self.fc2 = nn.Linear(1024, 512)
        self.ln2 = nn.LayerNorm(512)
        self.fc3 = nn.Linear(512, 256)
    def forward(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

_net = _Net()
_net.load_state_dict(torch.load(
    os.path.join(SUBMISSION, 'ptcg_baseline_model.pth'),
    map_location='cpu', weights_only=True
))
_net.eval()
_sub._model = _net

_norm = np.load(os.path.join(SUBMISSION, 'ptcg_normalization.npz'))
_sub._norm_mean = _norm['mean'].astype(np.float32)
_sub._norm_std  = _norm['std'].astype(np.float32)

print(f"[baseline agent] loaded ptcg_baseline_model.pth")


def agent(obs_dict):
    return _sub.agent(obs_dict)
