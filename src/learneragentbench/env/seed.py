"""Build a World from data files: a persona bundle, a skill graph and a task's InitialStateSpec.

Provenance is explicit: everything in the world comes from (1) the persona YAML, (2) the task's
memory list, (3) mastery overrides, (4) a named generator, (5) explicit record seeds — in that
order, so later sources can supersede earlier ones.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from ..schema import (
    RECORD_TYPES,
    Actor,
    AuthorizationPolicy,
    CalendarEvent,
    Course,
    InitialStateSpec,
    LABModel,
    MasteryState,
    MemoryEntry,
    PermissionLevel,
    Preference,
    SessionTranscript,
    SkillGraph,
    StudentProfile,
    new_id,
)
from .world import World


class PersonaBundle(LABModel):
    """A fictional student as authored in data/personas/<id>.yaml."""

    id: str
    profile: dict[str, Any]
    preferences: list[dict[str, Any]] = Field(default_factory=list)
    memory: list[dict[str, Any]] = Field(default_factory=list)
    policies: list[dict[str, Any]] = Field(default_factory=list)
    history: list[SessionTranscript] = Field(default_factory=list)
    mastery_defaults: dict[str, float] = Field(default_factory=dict)
    description: str = ""


def load_persona(path: str | Path) -> PersonaBundle:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return PersonaBundle.model_validate(data)


def load_skill_graph(path: str | Path) -> SkillGraph:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return SkillGraph.model_validate(data)


def _dt(v: Any, default: datetime) -> datetime:
    if v is None:
        return default
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


# ------------------------------------------------------------------ generators
Generator = Callable[[World, dict[str, Any]], None]
GENERATORS: dict[str, Generator] = {}


def generator(name: str) -> Callable[[Generator], Generator]:
    def deco(fn: Generator) -> Generator:
        GENERATORS[name] = fn
        return fn
    return deco


@generator("standard_semester")
def standard_semester(world: World, params: dict[str, Any]) -> None:
    """Courses plus their weekly fixed class meetings for ``weeks`` weeks from ``term_start``.

    params = {term_start: ISO date, weeks: int, courses: [{id, code, name, instructor_id, term,
              skill_ids, meetings: [{weekday: 0-6, start: "HH:MM", end: "HH:MM", location}]}]}
    """
    term_start = _dt(params.get("term_start"), world.now).replace(hour=0, minute=0, second=0, microsecond=0)
    weeks = int(params.get("weeks", 15))
    for c in params.get("courses", []):
        course = Course(id=c["id"], created_at=world.now, updated_at=world.now, code=c.get("code", c["id"]),
                        name=c["name"], instructor_id=c.get("instructor_id", ""), term=c.get("term", "term"),
                        skill_ids=c.get("skill_ids", []))
        world.add(course)
        for m in c.get("meetings", []):
            for w in range(weeks):
                day = term_start + timedelta(days=(int(m["weekday"]) - term_start.weekday()) % 7 + 7 * w)
                start = datetime.combine(day.date(), datetime.strptime(m["start"], "%H:%M").time())
                end = datetime.combine(day.date(), datetime.strptime(m["end"], "%H:%M").time())
                if end <= world.now - timedelta(days=int(params.get("keep_past_days", 14))):
                    continue
                world.add(CalendarEvent(
                    id=new_id("cal", f"{course.id}|{start.isoformat()}"), created_at=world.now, updated_at=world.now,
                    title=f"{course.code} class", start=start, end=end, event_kind="class", fixed=True,
                    location=m.get("location", ""), created_by=Actor.SYSTEM, linked={"course_id": course.id},
                ))


# ----------------------------------------------------------------- the builder
def build_world(spec: InitialStateSpec, persona: PersonaBundle, graph: SkillGraph, *,
                task_memory: list[dict[str, Any]] | None = None, path: str | Path | None = None,
                task_id: str = "") -> World:
    world = World.new(spec.now, path)
    now = world.now
    world.set_skill_graph(graph)
    world.store.kv_set("persona_id", persona.id)
    world.store.kv_set("task_id", task_id)

    # 1. profile
    prof_fields = dict(persona.profile)
    prof_fields.setdefault("id", persona.id)
    avail = prof_fields.get("availability")
    if isinstance(avail, dict) and "windows" not in avail:
        prof_fields["availability"] = {"windows": {int(k): v for k, v in avail.items()}}
    world.add(StudentProfile(created_at=now, updated_at=now, **prof_fields))

    # 2. preferences, memory, policies, as the persona states them
    for i, p in enumerate(persona.preferences):
        f = dict(p)
        f.setdefault("id", new_id("pref", f"{persona.id}|{f['key']}|{f.get('scope', 'global')}|{i}"))
        f["stated_at"] = _dt(f.get("stated_at"), now - timedelta(days=7))
        world.add(Preference(created_at=now, updated_at=now, **f))
    for i, m in enumerate(persona.memory):
        f = dict(m)
        f.setdefault("id", new_id("mem", f"{persona.id}|{i}|{f.get('text', '')[:40]}"))
        f["stated_at"] = _dt(f.get("stated_at"), now - timedelta(days=7))
        world.add(MemoryEntry(created_at=now, updated_at=now, **f))
    for i, pol in enumerate(persona.policies):
        f = dict(pol)
        f.setdefault("id", new_id("pol", f"{persona.id}|{f['action']}|{i}"))
        f["level"] = PermissionLevel(f["level"])
        f["granted_at"] = _dt(f.get("granted_at"), now - timedelta(days=7))
        world.add(AuthorizationPolicy(created_at=now, updated_at=now, **f))

    # 3. task-level memory (can supersede persona memory)
    for i, m in enumerate(task_memory or []):
        f = dict(m)
        f.setdefault("id", new_id("mem", f"{task_id}|{i}|{f.get('text', '')[:40]}"))
        f["stated_at"] = _dt(f.get("stated_at"), now - timedelta(days=1))
        entry = MemoryEntry(created_at=now, updated_at=now, **f)
        world.add(entry)
        sup = f.get("payload", {}).get("supersedes")
        if sup:
            old = world.get(MemoryEntry, sup)
            if old is not None:
                world.update(old.model_copy(update={"active": False, "superseded_by": entry.id}))

    # 4. mastery for every skill in the graph
    for s in graph.skills:
        if s.id in spec.mastery_overrides:
            m = float(spec.mastery_overrides[s.id])
        elif s.id in persona.mastery_defaults:
            m = float(persona.mastery_defaults[s.id])
        else:
            m = 0.3 if not s.prerequisites else 0.15
        world.add(MasteryState(id=new_id("mas", f"{persona.id}|{s.id}"), created_at=now, updated_at=now,
                               skill_id=s.id, mastery=m, stability_days=3.0,
                               last_practiced=now - timedelta(days=7) if m > 0 else None))

    # 5. generator, then explicit records
    if spec.generator:
        if spec.generator not in GENERATORS:
            raise KeyError(f"unknown generator {spec.generator!r}; known: {sorted(GENERATORS)}")
        GENERATORS[spec.generator](world, spec.generator_params)
    for seed in spec.records:
        cls = RECORD_TYPES[seed.kind]
        fields = dict(seed.fields)
        fields.setdefault("id", new_id(seed.kind[:4], f"{task_id}|{seed.kind}|{sorted(fields.items())!r}"))
        world.add(cls(created_at=now, updated_at=now, **fields))
    return world


def persona_system_summary(persona: PersonaBundle) -> str:
    """One paragraph a chatbot baseline can be given instead of tool access."""
    p = persona.profile
    bits = [f"{p.get('name', persona.id)} ({p.get('pronouns', 'they/them')}), {p.get('level', '')}, {p.get('program', '')}."]
    if p.get("goals"):
        bits.append("Goals: " + "; ".join(p["goals"]) + ".")
    return " ".join(bits)
