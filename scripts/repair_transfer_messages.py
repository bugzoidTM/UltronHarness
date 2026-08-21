"""Reconstrói o método de mensagens compactas do Transfer-100."""

from __future__ import annotations

import re
from pathlib import Path

path = Path("ultron/learning/transfer.py")
text = path.read_text(encoding="utf-8")
replacement = r'''    def _batch_messages(self, tasks: list[dict], procedures: list[str]) -> list[dict[str, str]]:
        procedure_block = "\n".join(f"- {item}" for item in procedures) or "- Nenhuma experiência prévia disponível."
        actions = "; ".join(f"{item['code']}: {item['description']}" for item in tasks[0]["actions"])
        cases = [f"{task['id']} | {task['objective']}" for task in tasks]
        return [
            {
                "role": "system",
                "content": "Executor local de benchmark. Não use internet nem exponha raciocínio privado. Devolva somente um objeto JSON que associe cada task_id à sua sequência de códigos. Exemplo: {\"configuration_repair_01\": \"I>R>V\"}. Use apenas códigos do respectivo caso e não inclua explicações.",
            },
            {
                "role": "user",
                "content": f"Experiência procedural disponível:\n{procedure_block}\n\nCatálogo de ações compartilhado:\n{actions}\n\nCasos públicos:\n" + "\n".join(cases),
            },
        ]

'''
pattern = r"    def _batch_messages\(.*?(?=    async def _score_batched)"
updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.DOTALL)
if count != 1:
    raise RuntimeError("Método _batch_messages não encontrado")
path.write_text(updated, encoding="utf-8")
