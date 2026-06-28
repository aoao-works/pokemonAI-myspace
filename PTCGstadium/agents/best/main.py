"""best エージェント: ptcg_rb_model.pth → ptcg_best_model.pth の優先順でロード"""
import os, sys, importlib.util
import torch, torch.nn as nn, torch.nn.functional as F, numpy as np

HERE       = os.path.dirname(os.path.abspath(__file__))
SUBMISSION = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'submission'))

_spec = importlib.util.spec_from_file_location('_sub_best', os.path.join(SUBMISSION, 'main.py'))
_sub  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sub)

class _Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(5658, 1024); self.ln1 = nn.LayerNorm(1024)
        self.fc2 = nn.Linear(1024, 512);  self.ln2 = nn.LayerNorm(512)
        self.fc3 = nn.Linear(512, 256)
    def forward(self, x):
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)

_net = _Net()
# ptcg_rb_model.pth (ルールベース特化) を優先、なければ ptcg_best_model.pth
for _candidate in ("ptcg_rb_model.pth", "ptcg_best_model.pth"):
    _p = os.path.join(SUBMISSION, _candidate)
    if os.path.exists(_p):
        _net.load_state_dict(torch.load(_p, map_location='cpu', weights_only=True))
        _net.eval()
        print(f"[best agent] loaded {_candidate}")
        break
_sub._model = _net
_norm = np.load(os.path.join(SUBMISSION, 'ptcg_normalization.npz'))
_sub._norm_mean = _norm['mean'].astype(np.float32)
_sub._norm_std  = _norm['std'].astype(np.float32)

def agent(obs_dict):
    return _sub.agent(obs_dict)
