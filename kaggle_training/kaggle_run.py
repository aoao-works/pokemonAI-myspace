"""
Kaggle自動学習スクリプト

使い方:
  python kaggle_training/kaggle_run.py          # 最新エピソードで学習・完了まで待機
  python kaggle_training/kaggle_run.py --push   # pushのみ（待機しない）
  python kaggle_training/kaggle_run.py --status # 現在のステータス確認

処理フロー:
  1. 最新エピソードデータセットを自動検索
  2. kernel-metadata.json を更新
  3. kaggle kernels push でアップロード・実行開始
  4. 完了まで60秒ごとにポーリング
  5. 出力ファイル（モデル・正規化パラメータ）を submission/ にコピー
"""

import json
import locale
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows: Python全体をUTF-8モードで動かす（kaggle APIがファイルを読む際も影響）
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ============================================================
# 設定
# ============================================================
ROOT        = Path(__file__).parent.parent      # pokemonAI-myspace/
KAGGLE_DIR  = Path(__file__).parent             # kaggle_training/
METADATA    = KAGGLE_DIR / 'kernel-metadata.json'
SUBMISSION  = ROOT / 'submission'
OUTPUT_DIR  = KAGGLE_DIR / 'output'

KERNEL_ID   = 'aoao0314/ptcg-weighted-training'
POLL_SEC    = 60    # ステータス確認間隔（秒）
TIMEOUT_MIN = 120   # タイムアウト（分）


# ============================================================
# Kaggle API 初期化
# ============================================================
def get_api():
    from kaggle import KaggleApi
    api = KaggleApi()
    api.authenticate()
    return api


# ============================================================
# 最新エピソードデータセットを取得
# ============================================================
def get_latest_episode_dataset(api) -> str:
    print('[1] 最新エピソードデータセットを検索中...')
    datasets = api.dataset_list(search='pokemon-tcg-ai-battle-episodes', user='kaggle')
    refs = [f'{d.ref}' for d in datasets if 'episodes-20' in str(d.ref)]
    if not refs:
        raise RuntimeError('エピソードデータセットが見つかりません')
    refs.sort(reverse=True)
    latest = refs[0]
    print(f'    最新: {latest}')
    return latest


# ============================================================
# kernel-metadata.json を更新
# ============================================================
def update_metadata(episode_dataset: str):
    print('[2] kernel-metadata.json を更新中...')
    with open(METADATA, encoding='utf-8') as f:
        meta = json.load(f)
    meta['dataset_sources']    = [episode_dataset]
    meta['competition_sources'] = ['pokemon-tcg-ai-battle']
    with open(METADATA, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f'    dataset_sources: {meta["dataset_sources"]}')


# ============================================================
# カーネルを push
# ============================================================
def push_kernel(api):
    print('[3] Kaggle にカーネルを push 中...')
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    result = subprocess.run(
        [sys.executable, '-m', 'kaggle', 'kernels', 'push', '-p', str(KAGGLE_DIR)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', env=env
    )
    output = result.stdout.strip() or result.stderr.strip()
    print(f'    {output}')
    if result.returncode != 0:
        raise RuntimeError(f'push 失敗: {output}')
    print('    push 完了')


# ============================================================
# ステータス確認
# ============================================================
def get_status(api) -> str:
    try:
        resp = api.kernels_status(KERNEL_ID)
        # KernelWorkerStatus enum → .name で "RUNNING" / "COMPLETE" / "ERROR" 等
        name = resp.status.name if hasattr(resp.status, 'name') else str(resp.status)
        msg  = resp.failure_message or ''
        return f'{name}  {msg}'.strip()
    except Exception as e:
        return f'FETCH_ERROR: {e}'


# ============================================================
# 完了まで待機
# ============================================================
def wait_for_completion(api) -> bool:
    print(f'[4] 実行待機中（{POLL_SEC}秒ごとに確認、最大{TIMEOUT_MIN}分）...')
    start    = time.time()
    deadline = start + TIMEOUT_MIN * 60

    while time.time() < deadline:
        status  = get_status(api)
        elapsed = int((time.time() - start) / 60)
        print(f'    [{elapsed:3d}分] {status}')

        if status.startswith('COMPLETE'):
            print('    完了!')
            return True
        if any(status.startswith(s) for s in ('ERROR', 'CANCEL')):
            print(f'    失敗: {status}')
            return False

        time.sleep(POLL_SEC)

    print(f'    タイムアウト（{TIMEOUT_MIN}分）')
    return False


# ============================================================
# 出力ファイルをダウンロード
# ============================================================
def download_output(api) -> bool:
    print('[5] 出力ファイルをダウンロード中...')
    OUTPUT_DIR.mkdir(exist_ok=True)
    api.kernels_output_cli(KERNEL_ID, path=str(OUTPUT_DIR), force=True)

    files = list(OUTPUT_DIR.glob('*'))
    if not files:
        print('    出力ファイルなし')
        return False

    print('    ダウンロード済みファイル:')
    for f in files:
        print(f'      {f.name}  ({f.stat().st_size / 1024 / 1024:.1f} MB)')
    return True


# ============================================================
# submission/ にコピー
# ============================================================
def copy_to_submission():
    print('[6] submission/ にモデルをコピー中...')
    copied = 0
    for fname in ['ptcg_baseline_model.pth', 'ptcg_normalization.npz']:
        src = OUTPUT_DIR / fname
        dst = SUBMISSION / fname
        if src.exists():
            shutil.copy2(src, dst)
            print(f'    {fname} → submission/{fname}  ({src.stat().st_size / 1024 / 1024:.1f} MB)')
            copied += 1
        else:
            print(f'    {fname} なし（スキップ）')
    print(f'    {copied} ファイルをコピー完了')


# ============================================================
# エラーログを表示
# ============================================================
def show_log(api):
    print('[ログ] カーネルログを取得中...')
    try:
        OUTPUT_DIR.mkdir(exist_ok=True)
        api.kernels_output_cli(KERNEL_ID, path=str(OUTPUT_DIR), force=True)
        for lf in OUTPUT_DIR.glob('*.log'):
            print(f'\n--- {lf.name} (末尾3000文字) ---')
            text = lf.read_text(encoding='utf-8', errors='replace')
            print(text[-3000:])
    except Exception as e:
        print(f'    ログ取得失敗: {e}')


# ============================================================
# メイン
# ============================================================
def main():
    args = sys.argv[1:]

    print('=' * 60)
    print(f'PTCG Kaggle自動学習  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 60)

    api = get_api()

    # ステータス確認のみ
    if '--status' in args:
        print(f'カーネル: {KERNEL_ID}')
        print(f'ステータス: {get_status(api)}')
        return

    # --download: 直接ダウンロードのみ
    if '--download' in args:
        ok = download_output(api)
        if ok:
            copy_to_submission()
        return

    push_only = '--push' in args

    try:
        episode_ds = get_latest_episode_dataset(api)
        update_metadata(episode_ds)
        push_kernel(api)

        if push_only:
            print('\npush完了。ステータス確認:')
            print('  python kaggle_training/kaggle_run.py --status')
            return

        success = wait_for_completion(api)

        if success:
            ok = download_output(api)
            if ok:
                copy_to_submission()
                print('\n完了! submission/ のモデルが更新されました。')
        else:
            show_log(api)
            print('\nエラーが発生しました。ログを確認してノートブックを修正後、再実行してください。')
            sys.exit(1)

    except Exception as e:
        print(f'\nエラー: {e}')
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
