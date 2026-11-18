# SIPL Language Toolkit

`CORE-01..06`, `VIS-01..02`, `REL-01` (10 балів)

## Модулі проєкту

- `grammar/sipl.lark` — граматика мови SIPL
- `src/sipl/ast.py` — типізоване AST, `SourceSpan` і класи помилок
- `src/sipl/parser.py` — парсер на основі `lark` (`ParseNode` + `AST`)
- `src/sipl/interpreter/` — виконання програм, стан змінних та подієвий trace
- `src/sipl/visualization/` — дерево виводу, AST та порівняння (`text`, `json`, `dot`, `svg`)
- `src/sipl/conformance.py` — запуск набору тестів відповідності
- `src/sipl/cli.py` — CLI інтерфейс
- `examples/` — приклади програм (`power.sipl`, `division.sipl`, `factorial.sipl`)
- `tests/` — тести (`test_core.py`, `test_vis.py`, `suite.json`)
- `docs/info.md` — коротко про граматику і формат `suite.json`
- `.github/workflows/ci.yml` — CI перевірки (`ruff`, `mypy`, тести, `conformance`)

## Приклади запуску CLI

```zsh
export PYTHONPATH=src
python -m sipl check examples/power.sipl --json
python -m sipl parse examples/power.sipl --concrete --json
python -m sipl run examples/power.sipl --state X=5,Y=2
python -m sipl trace examples/division.sipl --state X=7,Y=4 --json
python -m sipl viz examples/power.sipl --target parse-tree --format svg -o tree.svg
python -m sipl viz examples/power.sipl --target compare --format svg -o compare.svg
python -m sipl conformance --json
```

## Запуск тестів

```zsh
python -m unittest discover -s tests -v
```
