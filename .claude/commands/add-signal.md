---
description: 新しい信号（システム・帯域）を追加する手順
argument-hint: <signal name, e.g. navic_l1_sps>
---

信号 `$ARGUMENTS` を追加します。次の順で進め、各段階で何を根拠にしたかを報告してください。

1. **根拠となる文書を確認する。** ICDの名称・版・該当する表の番号を特定し、ユーザーに提示する。ICDが非公開なら、その旨を伝え、仮の符号（`random:` 系）で進めてよいか確認する。
2. **カタログを書く。** `src/snappnt/signals/catalog/$ARGUMENTS.yaml` に、搬送波周波数・チップレート・符号長・変調・データのシンボルレート・パイロットの有無・PRN範囲・出典（`source`）を書く。YAMLの数値は小数点付きで書く（例 `2492028000.0`）。
3. **符号生成器を書く。** `src/snappnt/signals/codes/` に生成器を追加し、`codes/__init__.py` の `_REGISTRY` に `code_family` 名で登録する。LFSRを使う場合は `codes/lfsr.py` の約束（初期値は出力される順に書く）に合わせる。
4. **ICD照合試験を書く。** `tests/test_codes_<system>.py` に、ICDに印刷された値（先頭チップの8進表記など）を書き写して照合する。期待値を生成器の出力から作ってはいけない。`@pytest.mark.icd` を付ける。
5. **一巡試験を足す。** 必要なら `scenarios/` にシナリオを追加し、`tests/test_loopback.py` に捕捉と正解照合の試験を追加する。
6. **決定を記録する。** 仮の値や判断があれば `docs/decisions.md` に追記する。
7. `/check` を実行して全試験が通ることを確認する。
