# Происхождение паттернов и границы

Это **новая самостоятельная реализация**, вдохновлённая инженерными идеями проектов ниже. Их код и файлы навыков в архив не копировались. Названия упомянуты только для атрибуции источников идей; файл не является официальным продуктом этих организаций.

- OpenAI skill-creator: https://github.com/openai/skills/tree/main/skills/.system/skill-creator — краткость, локальные scripts/references/assets, степенная детализация, валидация.
- Anthropic skill-creator: https://github.com/anthropics/skills/tree/main/skills/skill-creator — paired evals, количественная и качественная оценка, оптимизация триггеров, итерации.
- Superpowers writing-skills: https://github.com/obra/superpowers/tree/main/skills/writing-skills — RED/GREEN/REFACTOR, давления и проверка против рационализаций.
- Superpowers brainstorming: https://github.com/obra/superpowers/tree/main/skills/brainstorming — уточнение неопределённостей, сравнение вариантов и проверка нежелательного результата; адаптированные приёмы изложены в `references/design.md`.
- Gemini CLI skill-creator: https://github.com/google-gemini/gemini-cli/tree/main/packages/core/src/skills/builtin/skill-creator — инфраструктура создания навыков, портируемость, валидация/упаковка.
- Skill Forge: https://github.com/AgriciDaniel/skill-forge — составные рабочие процессы создания, ревью и эволюции навыков.
- Skill Seekers: https://github.com/yusufkaraaslan/Skill_Seekers — сбор и сравнение источников, конфликты, обобщение знаний.
- Agent Skills specification: https://agentskills.io/specification — формат, метаданные, структура.
- Документация Hermes: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills

**Отличия:** здесь реализованы собственные Python-скрипты без сторонних пакетов. Не включён Anthropic eval viewer, его LLM-grader, автоматические субагенты, crawler Skill Seekers или оригинальные инструменты OpenAI. Для их использования нужны отдельные среды; нельзя выдавать локальную имитацию за их полнофункциональный запуск.

Лицензии третьих сторон применяются к их собственным материалам. Если в будущем будет импортироваться код/текст из них, отдельно проверь license, условия атрибуции, совместимость и источник версии.
