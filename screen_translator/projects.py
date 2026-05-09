from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PyQt5.QtGui import QPixmap

from .config import APP_DIR, DEFAULT_PROMPT


HISTORY_DIR = APP_DIR / "history"
PROJECT_FILE = "translations.json"
TEMP_PROJECT_ID = "__temporary__"
TEMP_PROJECT_NAME = "临时翻译"


@dataclass
class TranslationRecord:
    round: int
    image_url: str
    original_text: str = ""
    translation: str = ""


@dataclass
class TranslationProject:
    project_id: str
    name: str
    prompt: str = DEFAULT_PROMPT
    path: Path | None = None
    is_temporary: bool = False
    records: list[TranslationRecord] = field(default_factory=list)

    def context_translations(self) -> list[str]:
        if self.is_temporary:
            return []
        context: list[str] = []
        for record in self.records:
            original = record.original_text.strip()
            translation = record.translation.strip()
            if record.round <= 0:
                continue
            if translation in {"正在翻译...", "正在重新翻译..."} or translation.startswith("翻译失败:"):
                continue
            if not original and not translation:
                continue
            if original:
                context.append(f"原文:\n{original}\n翻译:\n{translation}")
            elif translation:
                context.append(f"翻译:\n{translation}")
        return context


def _safe_project_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
    return cleaned or datetime.now().strftime("%Y-%m-%d-%H-%M-%S")


def _unique_project_path(name: str, existing: set[str] | None = None) -> Path:
    HISTORY_DIR.mkdir(exist_ok=True)
    existing = existing or set()
    safe_name = _safe_project_name(name)
    candidate = HISTORY_DIR / safe_name
    suffix = 2
    while candidate.exists() or candidate.name in existing:
        candidate = HISTORY_DIR / f"{safe_name}-{suffix}"
        suffix += 1
    return candidate


class ProjectStore:
    def __init__(self, default_prompt: str = DEFAULT_PROMPT, temp_prompt: str | None = None) -> None:
        self.default_prompt = default_prompt
        self.temp_project = TranslationProject(
            project_id=TEMP_PROJECT_ID,
            name=TEMP_PROJECT_NAME,
            prompt=temp_prompt or default_prompt,
            is_temporary=True,
            records=[TranslationRecord(round=0, image_url="", original_text="", translation=temp_prompt or default_prompt)],
        )
        self.projects: dict[str, TranslationProject] = {}
        self.load_projects()

    def all_projects(self) -> list[TranslationProject]:
        persistent = sorted(self.projects.values(), key=lambda project: project.name.lower())
        return [self.temp_project, *persistent]

    def get(self, project_id: str) -> TranslationProject:
        if project_id == TEMP_PROJECT_ID:
            return self.temp_project
        return self.projects[project_id]

    def load_projects(self) -> None:
        HISTORY_DIR.mkdir(exist_ok=True)
        self.projects.clear()
        for project_dir in HISTORY_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            project = self._load_project(project_dir)
            self.projects[project.project_id] = project

    def create_project(self, name: str | None = None, prompt: str | None = None) -> TranslationProject:
        project_name = name or datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        project_path = _unique_project_path(project_name)
        project_path.mkdir(parents=True, exist_ok=True)
        project = TranslationProject(
            project_id=project_path.name,
            name=project_path.name,
            prompt=prompt or self.default_prompt,
            path=project_path,
            records=[TranslationRecord(round=0, image_url="", original_text="", translation=prompt or self.default_prompt)],
        )
        self.projects[project.project_id] = project
        self.save_project(project)
        return project

    def rename_project(self, project_id: str, new_name: str) -> TranslationProject:
        project = self.get(project_id)
        if project.is_temporary or not project.path:
            return project

        safe_name = _safe_project_name(new_name)
        if safe_name == project.path.name:
            project.name = safe_name
            return project

        existing = {item.path.name for item in self.projects.values() if item.path and item.project_id != project_id}
        new_path = _unique_project_path(safe_name, existing=existing)
        project.path.rename(new_path)
        old_id = project.project_id
        project.project_id = new_path.name
        project.name = new_path.name
        project.path = new_path
        self.projects.pop(old_id, None)
        self.projects[project.project_id] = project
        self.save_project(project)
        return project

    def delete_project(self, project_id: str) -> None:
        project = self.get(project_id)
        if project.is_temporary or not project.path:
            return
        shutil.rmtree(project.path)
        self.projects.pop(project_id, None)

    def delete_last_record(self, project_id: str) -> TranslationRecord | None:
        project = self.get(project_id)
        records = [record for record in project.records if record.round > 0]
        if not records:
            return None

        record = max(records, key=lambda item: item.round)
        project.records = [item for item in project.records if item.round != record.round]

        image_path = self.image_path_for(project, record)
        if image_path and image_path.exists():
            image_path.unlink()

        if not project.is_temporary:
            self.save_project(project)
        return record

    def update_prompt(self, project_id: str, prompt: str) -> None:
        project = self.get(project_id)
        project.prompt = prompt
        if project.records:
            project.records[0].translation = prompt
        else:
            project.records.append(TranslationRecord(round=0, image_url="", original_text="", translation=prompt))
        if not project.is_temporary:
            self.save_project(project)

    def add_record(
        self,
        project_id: str,
        pixmap: QPixmap,
        original_text: str = "",
        translation: str = "",
    ) -> TranslationRecord:
        project = self.get(project_id)
        round_number = self._next_round(project)
        image_url = ""

        if not project.is_temporary and project.path:
            image_dir = project.path / "images"
            image_dir.mkdir(exist_ok=True)
            image_url = f"images/round_{round_number}.png"
            pixmap.save(str(project.path / image_url), "PNG")

        record = TranslationRecord(
            round=round_number,
            image_url=image_url,
            original_text=original_text,
            translation=translation,
        )
        project.records.append(record)
        if not project.is_temporary:
            self.save_project(project)
        return record

    def update_record_texts(
        self,
        project_id: str,
        round_number: int,
        original_text: str | None = None,
        translation: str | None = None,
    ) -> None:
        project = self.get(project_id)
        for record in project.records:
            if record.round == round_number:
                if original_text is not None:
                    record.original_text = original_text
                if translation is not None:
                    record.translation = translation
                break
        if not project.is_temporary:
            self.save_project(project)

    def update_record_translation(self, project_id: str, round_number: int, translation: str) -> None:
        self.update_record_texts(project_id, round_number, translation=translation)

    def image_path_for(self, project: TranslationProject, record: TranslationRecord) -> Path | None:
        if project.is_temporary or not project.path or not record.image_url:
            return None
        return project.path / record.image_url

    def save_project(self, project: TranslationProject) -> None:
        if project.is_temporary or not project.path:
            return
        project.path.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "round": record.round,
                "image_url": record.image_url,
                "original_text": record.original_text,
                "translation": record.translation,
            }
            for record in project.records
        ]
        (project.path / PROJECT_FILE).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_project(self, project_dir: Path) -> TranslationProject:
        records: list[TranslationRecord] = []
        file_path = project_dir / PROJECT_FILE
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                for item in data:
                    records.append(
                        TranslationRecord(
                            round=int(item.get("round", len(records))),
                            image_url=str(item.get("image_url", "")),
                            original_text=str(item.get("original_text", "")),
                            translation=str(item.get("translation", "")),
                        )
                    )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                records = []

        if not records:
            records = [TranslationRecord(round=0, image_url="", original_text="", translation=self.default_prompt)]

        return TranslationProject(
            project_id=project_dir.name,
            name=project_dir.name,
            prompt=records[0].translation or self.default_prompt,
            path=project_dir,
            records=records,
        )

    @staticmethod
    def _next_round(project: TranslationProject) -> int:
        rounds = [record.round for record in project.records]
        return max(rounds, default=0) + 1
