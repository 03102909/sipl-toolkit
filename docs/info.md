Короткий опис граматики SIPL та формату тестів відповідності

1. Граматика SIPL
   Файл grammar/sipl.lark описує синтаксис мови SIPL:

- Програма (NP1): begin <оператор> end
- Оператори (NS1..NS6): x := a, S1 ; S2, if b then S1 else S2, while b do S, begin S end, skip
- Арифметичні вирази (NA1..NA8): n, x, +, -, \*, div, mod, (a), унарний -
- Умови (NB1..NB10): =, >, >=, <, <=, !=, not/¬, and/∧, or/∨, (b)
- Лексика: змінні [A-Za-z\_][A-Za-z0-9_]_ (крім ключових слів), цілі числа, коментарі #, //, /_ ... \*/.

2. Формат тестів відповідності (tests/suite.json)
   Кожен тест у масиві cases містить:

- id: назва тесту
- category: execution | runtime_error | syntax_error
- source: текст SIPL-програми
- initial_state: словник початкових значень змінних
- max_steps: ліміт кроків (опціонально)
- expected: exit_code (0 успіх, 1 runtime, 2 syntax), final_state, частковий зразок ast, error_code, error_line

Запуск зовнішньої реалізації CLI:
sipl conformance --cmd "python -m sipl" --json

Коди завершення CLI:
0 - успіх
1 - помилка виконання (RUN001 неініціалізована змінна, RUN002 ділення на 0, RUN003 ліміт кроків) або провал conformance
2 - синтаксична або лексична помилка (LEX*, SYN*)
3 - помилка аргументів чи файлу (CLI001)
