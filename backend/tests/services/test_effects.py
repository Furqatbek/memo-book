"""A76: the domain declares side effects; something must actually run them.

The bug these exist to prevent already shipped once. `Effect.ALERT_OPERATOR`
was declared on entering `render_failed` from the day the state machine was
written, and no code anywhere executed it — the one place that received it
wrote a log line and a comment promising the wiring later. A paid order could
fail to render with the customer waiting and nobody told.

The registry test below is the part that matters: it fails when an effect is
declared without an executor, which is the moment the mistake is cheap.
"""
from types import SimpleNamespace

import pytest

from app.domain.states import EFFECTS_ON_ENTER, Effect, OrderStatus
from app.services.effects import EXECUTORS, When, declared_effects, run_effects


class TestNoEffectIsDeclaredWithoutAnExecutor:
    def test_every_declared_effect_has_one(self):
        missing = declared_effects() - set(EXECUTORS)
        assert not missing, (
            f"the state machine declares {sorted(e.value for e in missing)} "
            "but nothing runs them — a status change with no consequence")

    def test_the_registry_has_no_executors_for_nothing(self):
        """An executor for an effect no status declares is dead code that
        reads like a working feature."""
        stale = set(EXECUTORS) - declared_effects()
        assert not stale, f"executors nothing can trigger: {sorted(stale)}"

    def test_alert_operator_specifically(self):
        """The one that was missing. Named on its own so a regression says
        so directly rather than as part of a set difference."""
        assert Effect.ALERT_OPERATOR in EXECUTORS
        assert Effect.ALERT_OPERATOR in EFFECTS_ON_ENTER[OrderStatus.RENDER_FAILED]

    def test_every_effect_in_the_enum_is_reachable(self):
        """An effect in the enum that no status declares is either a missing
        transition or a leftover."""
        unreachable = set(Effect) - declared_effects()
        assert not unreachable, (
            f"{sorted(e.value for e in unreachable)} can never happen")


# run_effects only reads human_ref, for the log line.
_ORDER = SimpleNamespace(human_ref="UB-TEST1")


class TestTimingIsPartOfTheContract:
    """Two effects here sit on opposite sides of one commit, and putting
    either on the wrong side is a silent data race rather than an error."""

    def test_the_outbox_effects_run_inside_the_transaction(self):
        """An outbox row committed separately from the status it announces
        breaks the transactional-outbox guarantee in both directions."""
        for effect in (Effect.NOTIFY_PRODUCTION, Effect.ALERT_OPERATOR):
            when, _ = EXECUTORS[effect]
            assert when is When.IN_TRANSACTION, f"{effect} must be atomic"

    def test_the_render_job_is_dispatched_after_the_commit(self):
        """Enqueue before committing and the worker can read the order in its
        pre-paid state and do nothing, rarely, under load."""
        when, _ = EXECUTORS[Effect.ENQUEUE_RENDER]
        assert when is When.AFTER_COMMIT

    async def test_an_effect_for_the_other_side_is_skipped_not_run(self, db):
        """run_effects takes the whole tuple both times and picks. Callers
        splitting the tuple themselves is how one gets dropped."""
        ran = []
        original = EXECUTORS[Effect.ENQUEUE_RENDER]

        async def spy(session, order, context):
            ran.append("enqueue")

        EXECUTORS[Effect.ENQUEUE_RENDER] = (When.AFTER_COMMIT, spy)
        try:
            await run_effects(db, _ORDER, (Effect.ENQUEUE_RENDER,),
                              When.IN_TRANSACTION)
            assert ran == []
            await run_effects(db, _ORDER, (Effect.ENQUEUE_RENDER,),
                              When.AFTER_COMMIT)
            assert ran == ["enqueue"]
        finally:
            EXECUTORS[Effect.ENQUEUE_RENDER] = original


class TestAnUnknownEffectIsLoud:
    async def test_it_raises_rather_than_being_ignored(self, db):
        """If the registry test is ever bypassed, dropping the effect quietly
        is the one outcome that must not happen: this is the money path."""
        original = EXECUTORS.pop(Effect.ALERT_OPERATOR)
        try:
            with pytest.raises(RuntimeError, match="no executor"):
                await run_effects(db, _ORDER, (Effect.ALERT_OPERATOR,),
                                  When.IN_TRANSACTION)
        finally:
            EXECUTORS[Effect.ALERT_OPERATOR] = original
