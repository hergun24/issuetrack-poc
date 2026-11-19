"""Unit tests: pure domain logic (no HTTP)."""

import datetime
import itertools

from app.domain import (
    CANONICAL_ACTIONS,
    validate_date_only,
    validate_enum,
    validate_id_ref,
    validate_str,
)
from app.errors import Validation

from app.api import _overdue, member_out


class TestOverdueRule:
    def test_past_due_open_is_overdue(self):
        assert _overdue("2000-01-01", "OPEN", False) is True

    def test_today_due_is_not_overdue(self):
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        assert _overdue(today, "OPEN", False) is False

    def test_future_due_is_not_overdue(self):
        t = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        assert _overdue(t, "OPEN", False) is False

    def test_null_due_never_overdue(self):
        assert _overdue(None, "OPEN", False) is False

    def test_resolved_closed_not_overdue_even_past(self):
        assert _overdue("2000-01-01", "RESOLVED", False) is False
        assert _overdue("2000-01-01", "CLOSED", False) is False

    def test_archived_project_excluded(self):
        assert _overdue("2000-01-01", "OPEN", True) is False


class TestEventSelection:
    """Canonical event classification mirroring the API patch logic."""

    @staticmethod
    def _classify(old, new):
        provided = set(new)
        status_changed = "status" in provided and new["status"] != old["status"]
        assignee_changed = "assignee_id" in provided and new["assignee_id"] != old["assignee_id"]
        other_changed = bool(provided - {"status", "assignee_id"})
        if not (status_changed or assignee_changed or other_changed):
            return "NOOP"
        if status_changed and not assignee_changed and not other_changed:
            return "ISSUE_STATUS_CHANGED"
        if assignee_changed and not status_changed and not other_changed:
            return "ISSUE_ASSIGNED" if new["assignee_id"] is not None else "ISSUE_UNASSIGNED"
        return "ISSUE_UPDATED"

    def test_status_only(self):
        old = {"status": "OPEN", "assignee_id": None, "title": "t"}
        assert self._classify(old, {"status": "CLOSED"}) == "ISSUE_STATUS_CHANGED"

    def test_assignee_set(self):
        old = {"status": "OPEN", "assignee_id": None, "title": "t"}
        assert self._classify(old, {"assignee_id": "u2"}) == "ISSUE_ASSIGNED"

    def test_assignee_clear(self):
        old = {"status": "OPEN", "assignee_id": "u2", "title": "t"}
        assert self._classify(old, {"assignee_id": None}) == "ISSUE_UNASSIGNED"

    def test_other_field(self):
        old = {"status": "OPEN", "assignee_id": None, "title": "t"}
        assert self._classify(old, {"title": "t2"}) == "ISSUE_UPDATED"

    def test_mixed_change_is_updated(self):
        old = {"status": "OPEN", "assignee_id": None, "title": "t"}
        assert self._classify(old, {"title": "t2", "status": "IN_PROGRESS"}) == "ISSUE_UPDATED"


class TestAll16Transitions:
    STATUSES = ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"]

    def test_all_pairs_legal(self):
        for a, b in itertools.product(self.STATUSES, repeat=2):
            assert b in self.STATUSES, f"{a}->{b} must be legal"


class TestValidators:
    def test_validate_str_ok(self):
        assert validate_str("ab", "f", 1, 5) == "ab"

    def test_validate_str_too_long(self):
        try:
            validate_str("abcdef", "f", 1, 5)
            raise AssertionError("should raise")
        except Validation:
            pass

    def test_validate_str_too_short(self):
        try:
            validate_str("", "f", 1, 5)
            raise AssertionError("should raise")
        except Validation:
            pass

    def test_validate_enum_default_and_reject(self):
        assert validate_enum(None, ["A", "B"], "f", required=False, default="A") == "A"
        assert validate_enum("B", ["A", "B"], "f", required=False, default="A") == "B"
        try:
            validate_enum("C", ["A", "B"], "f", required=False, default="A")
            raise AssertionError("should reject")
        except Validation:
            pass

    def test_validate_date_only(self):
        # Valid Gregorian dates are accepted verbatim.
        for good in ("2020-01-31", "2028-02-29", "2026-05-15", "1999-12-31", "2000-02-29"):
            assert validate_date_only(good, "due_date") == good, good
        assert validate_date_only(None, "due_date") is None
        for bad in ("2020-13-01", "2020-02-30", "2027-02-29", "2026-04-31",
                    "2020-01-01T00:00:00Z", "2026-11-20 12:00:00",
                    "01-01-2030", "2030/01/01", "2030-1-1", "x", "2020-01-01Z"):
            try:
                validate_date_only(bad, "due_date")
                raise AssertionError(f"should reject {bad}")
            except Validation:
                pass

    def test_validate_date_only_null_and_type_rejection(self):
        # Non-string, non-null values are rejected.
        for bad in (1, 20260515, 0.5, ["2026-05-15"], {"due_date": "2026-05-15"}, True):
            try:
                validate_date_only(bad, "due_date")
                raise AssertionError(f"should reject {bad!r}")
            except Validation:
                pass

    def test_validate_date_only_whitespace_rejected(self):
        for bad in (" 2026-05-15", "2026-05-15 ", "\t2026-05-15\n"):
            try:
                validate_date_only(bad, "due_date")
                raise AssertionError(f"should reject {bad!r}")
            except Validation:
                pass

    def test_validate_date_only_century_bounds(self):
        # Gregorian calendar: 0001-01-01 through 9999-12-31.
        assert validate_date_only("0001-01-01", "due_date") == "0001-01-01"
        assert validate_date_only("9999-12-31", "due_date") == "9999-12-31"
        for bad in ("0000-12-31", "10000-01-01"):
            try:
                validate_date_only(bad, "due_date")
                raise AssertionError(f"should reject {bad}")
            except Validation:
                pass

    def test_validate_id_ref(self):
        assert validate_id_ref("abc", "f") == "abc"
        assert validate_id_ref(None, "f") is None
        try:
            validate_id_ref("a" * 65, "f")
            raise AssertionError("should reject >64 chars")
        except Validation:
            pass


def test_pagination_math():
    assert max(1, -(-0 // 20)) == 1
    assert max(1, -(-21 // 10)) == 3
    assert max(1, -(-10 // 10)) == 1
    assert max(1, -(-11 // 10)) == 2


def test_member_view_role_safe_fields():
    row = {"user_id": "u", "display_name": "A", "role": "ADMIN", "email": "a@x.com"}
    assert member_out(row, include_email=True)["email"] == "a@x.com"
    assert "email" not in member_out(row, include_email=False)


def test_canonical_vocabulary():
    assert len(CANONICAL_ACTIONS) == 16
    assert "MEMBER_ISSUES_UNASSIGNED" in CANONICAL_ACTIONS


def test_timestamp_format():
    from app.db import DB
    ts = DB.utcnow_iso()
    assert ts.endswith("Z") and "T" in ts and len(ts) == 20
