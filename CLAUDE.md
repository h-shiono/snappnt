# CLAUDE.md

このファイルは、このリポジトリで作業するClaude Code向けの指示です。人間の開発者が読んでも分かるように書いています。

## プロジェクトの目的

snappnt は、安価な受信フロントエンド（ESP32のESP-SDR、HackRF、USRP）で衛星測位信号を「短時間だけ取り込み、後から捕捉する」ための道具一式です。シミュレータと受信処理を同じリポジトリに置き、シミュレータが仕込んだ正解と受信結果を自動で照合できるようにしています。

- 最初の対象：NavIC S帯 SPS（2492.028 MHz、BPSK(1)、ICD公開）
- 将来の対象：C帯LEO-PNT（5010–5030 MHz、外部ミキサで2.4 GHz帯へ変換）ほか

## コマンド

```bash
pip install -e ".[dev]"          # 開発用インストール（ハードウェアを使うときは ".[dev,hw]"）
pytest -q                        # 全試験
pytest -m icd -q                 # ICDの表との照合だけ
pytest -m loopback -q            # シミュレータ→捕捉→正解照合の一巡試験だけ
ruff check . && ruff format .    # 静的検査と整形
snappnt info                     # 登録済みの信号と機材
snappnt sim scenarios/navic_s_esp32c3.yaml -o out/c3
snappnt acquire out/c3 --prn 10 --freq-span 40000
snappnt sweep scenarios/navic_s_esp32c3.yaml --cn0 48:60:2 --trials 20 -o out/pd.csv
```

変更を終えたら、必ず `ruff check .`、`ruff format --check .`、`pytest -q` を通してください。

## 構成（詳しくは docs/architecture.md）

| 場所 | 役割 |
|---|---|
| `src/snappnt/signals/` | どの信号を受けるか。`catalog/*.yaml` にパラメータ、`codes/` に拡散符号の生成器 |
| `src/snappnt/frontend/` | どう受けるか。`devices/*.yaml` に機材の制約、`freqplan.py` にミキサを含む周波数配置 |
| `src/snappnt/io/` | 層の間のデータ受け渡し。SigMF、ESP-SDRの32ビット語、発生器のコマンド組み立て |
| `src/snappnt/sim/` | 正解付きの信号を作る。シナリオ、劣化（量子化・水晶ずれ・取り込み長）、再生用ファイル |
| `src/snappnt/rx/` | 捕捉。1周期より短い取り込みにも対応した並列コード探索 |
| `src/snappnt/eval/` | 捕捉確率とC/N0の関係、正解との照合 |
| `scenarios/` | 試験条件のYAML |
| `docs/` | 設計、有線試験の手順、決定記録、マイルストーン |

## 守るべき規約

1. **単位は変数名に付ける。** `_hz`、`_s`、`_sps`、`_dbhz`、`_chips`、`_ppm` など。単位はSI（周波数はHz、時間は秒）。
2. **符号は ±1 の int8。** ビットとの対応は 0 → +1、1 → −1（GNSSの慣例）。
3. **複素ベースバンドは complex64。** 雑音は1サンプルあたり分散1で、N0 = 1/fs とする（`sim/generate.py` 冒頭の説明を参照）。
4. **コード位相は「取り込み先頭サンプルでのチップ位置」。** 周波数ずれは「周波数配置で決まる中心（baseband_offset_hz）からの差」。シミュレータの正解とrxの出力はこの定義で揃える。
5. **新しい信号を追加するときは、ICDとの照合試験を必ず付ける。** ICDに印刷された値（先頭チップの8進表記など）を、生成器とは独立に試験ファイルへ書き写す。生成器の出力から期待値を作ってはいけない。ICDが非公開の信号は `random:` 系の仮の符号を使い、YAMLの `source` に仮であることを書く。
6. **送信は絶対に自動で行わない。** `hackrf_transfer` や `tx_samples_from_file` を実行しない（`.claude/settings.json` で禁止済み）。snappnt は再生用のファイルとコマンド文字列を作るところまで。送信は人が、ケーブルとアッテネータで閉じた経路を確認してから行う（docs/conducted-test.md）。
7. **大きなデータはコミットしない。** `out/` と `data/` 以下のSigMFや再生用ファイルは .gitignore 済み。試験は小さなシナリオをその場で生成して使う。

## 文章の書き方（コード内コメント、docs、コミットメッセージ、Claudeの返答すべて）

- docs と返答は日本語、コード内のコメントとdocstringは英語。
- **英語を直訳した造語を作らない。** 定着した用語（捕捉、追尾、コード位相、C/N0 など）を使い、定着した訳語がない概念は、その場で短い説明を添える。
- **要約を重ねて情報を圧縮しない。** 前に書いたことを縮めた言い回しで参照せず、必要なら何を指すかを書き直す。読み手が過去の文脈を覚えている前提にしない。
- 未確認の値は `TODO` と「何を確認すれば決まるか」を書く。推測を確定値のように書かない。
- 設計上の判断をしたら `docs/decisions.md` に1項目追加する（何を決めたか、なぜか、他の選択肢）。

## 未確定事項（作業中に確定したら更新すること）

- ESP-SDRファームウェアのライセンス（フォーク前に確認）
- ESP32-C3の1回あたりの最大取り込みサンプル数（`frontend/devices/esp32c3.yaml` は仮に16384）
- ESP-SDRのチューニング・取り込みコマンドの正確な書式と、ホストへの転送形式（`io/espsdr_client.py`）
- C61の低サンプルレートが「クロック分周のみ（帯域制限なし）」かどうか（雑音の折り返し損失に直結）
- B206mini-i の仕様（`frontend/devices/b206mini_i.yaml`）
