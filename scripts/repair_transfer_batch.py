"""Repara a implementação do método batched do Transfer-100."""

from __future__ import annotations

import re
from pathlib import Path

path = Path("ultron/learning/transfer.py")
text = path.read_text(encoding="utf-8")
replacement = r'''    async def _score_batched(self, experienced: bool) -> tuple[float, dict[str, float], list[dict]]:
        corpus = [item for entries in self.origin_corpus.values() for item in entries] if experienced else []
        self.dataset.assert_isolated(corpus)
        answers, tasks = self.dataset.private_answers(), self.dataset.public_tasks()
        grouped: dict[str, list[dict]] = defaultdict(list)
        for task in tasks:
            grouped[str(task["family"])].append(task)
        hits: dict[str, list[bool]] = defaultdict(list)
        traces: list[dict] = []
        for family, family_tasks in sorted(grouped.items()):
            selected = self.origin_corpus.get(family, []) if experienced else []
            parsed: dict[str, str] = {}
            batch_outputs: list[str] = []
            known_ids = {str(task["id"]) for task in family_tasks}
            for start in range(0, len(family_tasks), self.batch_size):
                chunk = family_tasks[start : start + self.batch_size]
                reply = await self.models.generate(
                    self._batch_messages(chunk, selected),
                    self.model_name,
                    seed=self.seed,
                    max_tokens=max(96, 28 * len(chunk)),
                )
                batch_outputs.append(reply.content)
                for line in reply.content.splitlines():
                    if "=" not in line:
                        continue
                    task_id, raw = line.split("=", 1)
                    task_id = task_id.strip()
                    if task_id in known_ids:
                        parsed[task_id] = self._normalise_plan(raw)
            public_output = "\\n--- batch ---\\n".join(batch_outputs)
            for task in family_tasks:
                expected = str(answers[task["id"]]["expected_sequence"]).upper()
                actual = parsed.get(str(task["id"]), "")
                ok = actual == expected
                hits[family].append(ok)
                traces.append(
                    {
                        "task_id": task["id"],
                        "family": family,
                        "expected": expected,
                        "actual": actual,
                        "success": ok,
                        "mode": "experienced" if experienced else "fresh",
                        "execution": "batched_by_family",
                        "batch_output": public_output,
                    }
                )
        family_scores = {name: round(sum(values) / len(values), 4) for name, values in hits.items()}
        return round(sum(sum(values) for values in hits.values()) / len(tasks), 4), family_scores, traces

'''
pattern = r"    async def _score_batched\(.*?(?=    async def _score\(self, experienced: bool\))"
updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
if count != 1:
    raise RuntimeError("Método _score_batched não encontrado para reparo")
path.write_text(updated, encoding="utf-8")
