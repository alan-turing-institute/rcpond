"""A read-only ServiceNow interface backed by pre-downloaded HTML files.

Provides ``HtmlServiceNow``, a subclass of ``ServiceNow`` that reads ticket
data from a directory of HTML export files (produced by the
``/x_tati_resmgt_research.do?...`` endpoint) instead of making live API calls.

Public API
----------
- ``HtmlServiceNow(html_dir)``: Construct from a directory of ``*.html`` files.
- All read methods from ``ServiceNow`` are supported:
  ``get_tickets()``, ``get_ticket()``, ``get_full_ticket()``, ``get_work_notes()``.
- Write methods (``post_note()``, ``assign_to()``) are no-ops.
- ``get_assignee()`` returns an empty assignee dict — assignment state is not
  stored in the HTML export.

Return types
------------
Same as ``ServiceNow``: ``list[Ticket]``, ``Ticket``, ``FullTicket``, ``list[str]``.

Configuration
-------------
No ``Config`` object is needed. Pass the directory path directly.
"""

import dataclasses
from pathlib import Path

from rcpond.parse_html import extract_key_facts
from rcpond.servicenow import FullTicket, ServiceNow, Ticket

_SHORT_DESCRIPTION = "Request access to HPC and cloud computing facilities"


## ---- Internal helpers ----


def _or_empty(value: str | None) -> str:
    """Return ``value`` or an empty string when ``value`` is ``None``."""
    return value if value is not None else ""


def _facts_to_ticket(facts: dict, html_file: Path) -> Ticket:
    """Build a ``Ticket`` from the result of ``extract_key_facts``.

    Parameters
    ----------
    facts : dict
        Output of ``extract_key_facts``.
    html_file : Path
        Source file; its stem is used as a stand-in for ``sys_id``.

    Returns
    -------
    Ticket
    """
    activities = facts["activities"]

    ## Use the earliest activity date as a best-effort stand-in for opened_at
    opened_at = ""
    if not activities.empty and activities["date"].notna().any():
        opened_at = _or_empty(activities["date"].dropna().min())

    return Ticket(
        sys_id=_or_empty(facts.get("sys_id")) or html_file.stem,
        number=_or_empty(facts.get("ticket_number")),
        opened_at=opened_at,
        requested_for=_or_empty(facts.get("requested_for")),
        u_category=_or_empty(facts.get("category")),
        u_sub_category=_or_empty(facts.get("sub_category")),
        short_description=_SHORT_DESCRIPTION,
    )


def _facts_to_full_ticket(tkt: Ticket, facts: dict) -> FullTicket:
    """Build a ``FullTicket`` from a ``Ticket`` and ``extract_key_facts`` output.

    Parameters
    ----------
    tkt : Ticket
        Base ticket (already constructed from the same HTML file).
    facts : dict
        Output of ``extract_key_facts``.

    Returns
    -------
    FullTicket
    """
    extra_fields = {f.name for f in dataclasses.fields(FullTicket)} - {f.name for f in dataclasses.fields(Ticket)}
    extra_values = {
        "work_notes": facts.get("work_notes", ""),
        "project_title": _or_empty(facts.get("project_title")),
        "research_area_programme": _or_empty(facts.get("research_area_or_programme")),
        "if_other_please_specify": "",  ## handled by parse_html's fallback logic
        "pi_supervisor_name": _or_empty(facts.get("pi_or_supervisor")),
        "pi_supervisor_email": _or_empty(facts.get("pi_or_supervisor_email")),
        "which_service": _or_empty(facts.get("platform_choice")),
        "subscription_type": _or_empty(facts.get("subscription_type")),
        "which_finance_code": _or_empty(facts.get("finance_code")),
        "pmu_contact_email": _or_empty(facts.get("pmu_contact_email")),
        "credits_requested": _or_empty(facts.get("credits_requested")),
        "which_facility": _or_empty(facts.get("which_facility")),
        "if_other_please_specify_facility": "",
        "cpu_hours_required": _or_empty(facts.get("cpu_hours_required")),
        "gpu_hours_required": _or_empty(facts.get("gpu_hours_required")),
        "new_or_existing_allocation": _or_empty(facts.get("new_or_existing_allocation")),
        "azure_subscription_id_or_hpc_group_project_id": _or_empty(
            facts.get("azure_subscription_id_or_hpc_group_project_id")
        ),
        "start_date": _or_empty(facts.get("start_date")),
        "end_date": _or_empty(facts.get("end_date")),
        "data_sensitivity": _or_empty(facts.get("data_sensitivity")),
        "platform_justification": _or_empty(facts.get("platform_justification")),
        "research_justification": _or_empty(facts.get("research_justification")),
        "computational_requirements": _or_empty(facts.get("computational_requirements")),
        "users_who_require_access_names_and_emails": _or_empty(facts.get("users_who_require_access_names_and_emails")),
        "cost_compute_time_breakdown": _or_empty(facts.get("cost_compute_time_breakdown")),
    }

    ## Guard against FullTicket gaining new fields not yet mapped here
    unmapped = extra_fields - set(extra_values)
    if unmapped:
        err_msg = f"FullTicket has unmapped fields: {unmapped}"
        raise NotImplementedError(err_msg)

    return FullTicket.from_Ticket(tkt, **extra_values)


## ---- Interface to this module ----


class HtmlServiceNow(ServiceNow):
    """Read-only ServiceNow interface backed by a directory of HTML export files.

    >>> sn = HtmlServiceNow(Path("downloads/"))
    >>> sn.get_tickets()
    """

    def __init__(self, html_dir: Path) -> None:
        ## Do NOT call super().__init__() — no Config or HTTP session is needed
        html_dir = Path(html_dir)
        if not html_dir.exists():
            msg = f"Input directory does not exist: {html_dir}"
            raise FileNotFoundError(msg)
        if not html_dir.is_dir():
            msg = f"Input path is not a directory: {html_dir}"
            raise NotADirectoryError(msg)
        if not any(html_dir.glob("*.html")):
            msg = f"No .html files found in: {html_dir}"
            raise ValueError(msg)
        self._html_dir = html_dir

    def _find_html_for_ticket(self, tkt: Ticket) -> Path:
        """Locate the HTML file for ``tkt``.

        Parameters
        ----------
        tkt : Ticket
            The ticket to look up.

        Returns
        -------
        Path
            Path to the matching HTML file.

        Raises
        ------
        FileNotFoundError
            If no HTML file for the ticket number is found in ``html_dir``.
        """
        ## Try the conventional filename produced by download_tickets.sh first
        candidate = self._html_dir / f"ticket_{tkt.number}.html"
        if candidate.exists():
            return candidate

        ## Fall back to scanning all HTML files by parsed ticket number
        for f in self._html_dir.glob("*.html"):
            facts = extract_key_facts(f)
            if facts.get("ticket_number") == tkt.number:
                return f

        err_msg = f"No HTML file found for ticket {tkt.number} in {self._html_dir}"
        raise FileNotFoundError(err_msg)

    ## ---- Read methods ----

    def get_tickets(self, include_assigned_tickets: bool = False) -> list[Ticket]:
        """Return a ``Ticket`` for each HTML file in ``html_dir``.

        Parameters
        ----------
        include_assigned_tickets : bool
            If ``False`` (default), only unassigned tickets are returned.
            If ``True``, all tickets are returned regardless of assignment state.

        Returns
        -------
        list[Ticket]
        """
        tickets = []
        for f in sorted(self._html_dir.glob("*.html")):
            facts = extract_key_facts(f)
            is_assigned = bool(facts["assigned_to"]["display_value"])
            if is_assigned and not include_assigned_tickets:
                continue
            tickets.append(_facts_to_ticket(facts, f))
        return tickets

    def get_full_ticket(self, tkt: Ticket) -> FullTicket:
        """Parse the HTML file for ``tkt`` and return a ``FullTicket``.

        Parameters
        ----------
        tkt : Ticket
            The ticket to look up.

        Returns
        -------
        FullTicket
        """
        html_file = self._find_html_for_ticket(tkt)
        facts = extract_key_facts(html_file)
        return _facts_to_full_ticket(tkt, facts)

    def get_work_notes(self, tkt: Ticket) -> list[str]:
        """Return the work notes for ``tkt`` extracted from the HTML activity log.

        Parameters
        ----------
        tkt : Ticket
            The ticket to look up.

        Returns
        -------
        list[str]
            One entry per work note, in chronological order.
        """
        html_file = self._find_html_for_ticket(tkt)
        facts = extract_key_facts(html_file)
        activities = facts["activities"]
        return list(activities[activities["field_name"] == "work_notes"]["text"].dropna())

    def get_assignee(self, tkt: Ticket) -> dict[str, str]:
        """Return the assignee for ``tkt`` extracted from the HTML.

        Parameters
        ----------
        tkt : Ticket
            The ticket to look up.

        Returns
        -------
        dict[str, str]
            Dict with ``"value"`` (sys_id) and ``"display_value"`` (name).
            Both are empty strings if the ticket is unassigned.
        """
        html_file = self._find_html_for_ticket(tkt)
        facts = extract_key_facts(html_file)
        return facts["assigned_to"]

    ## ---- Write no-ops ----

    def post_note(self, _tkt: Ticket, _note: str) -> None:
        """No-op — HTML source is read-only."""

    def _attempt_assign_to(self, _ticket: Ticket, _assignee: str) -> None:
        """No-op — HTML source is read-only."""

    def assign_to(self, _ticket: Ticket, _assignee: str) -> dict[str, str]:
        """No-op — HTML source is read-only. Returns an empty assignee dict."""
        return {"value": "", "display_value": ""}
