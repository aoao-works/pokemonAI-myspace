"""
RL学習モデル (ptcg_rl_model.pth) を使うエージェントラッパー。
submission/main.py は ptcg_rl_model.pth を自動優先するのでそのまま使う。
"""
import os, sys, importlib.util

HERE       = os.path.dirname(os.path.abspath(__file__))
SUBMISSION = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'submission'))

# submission/main.py を独立したモジュールとして読み込む
# _load_model() が ptcg_rl_model.pth を自動的に優先する
_spec = importlib.util.spec_from_file_location('_sub_rl', os.path.join(SUBMISSION, 'main.py'))
_sub  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sub)

print(f"[rl agent] loaded model from {SUBMISSION}")


def agent(obs_dict):
    return _sub.agent(obs_dict)
