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

from pathlib import Path

from rcpond.parse_html import extract_key_facts, parse_ticket_html
from rcpond.servicenow import FullTicket, ServiceNow, Ticket

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
        """Return a ``FullTicket`` for each HTML file in ``html_dir``.

        Parameters
        ----------
        include_assigned_tickets : bool
            If ``False`` (default), only unassigned tickets are returned.
            If ``True``, all tickets are returned regardless of assignment state.

        Returns
        -------
        list[Ticket]
            Each element is actually a ``FullTicket``.
        """
        tickets: list[Ticket] = []
        for f in sorted(self._html_dir.glob("*.html")):
            facts = extract_key_facts(f)
            is_assigned = bool(facts["assigned_to"]["display_value"])
            if is_assigned and not include_assigned_tickets:
                continue
            tickets.append(parse_ticket_html(f))
        return tickets

    def get_full_ticket(self, tkt: Ticket) -> FullTicket:
        """Return a ``FullTicket`` for ``tkt``.

        If ``tkt`` is already a ``FullTicket`` (as returned by ``get_tickets``),
        it is returned directly. Otherwise the HTML file is parsed.

        Parameters
        ----------
        tkt : Ticket
            The ticket to look up.

        Returns
        -------
        FullTicket
        """
        if isinstance(tkt, FullTicket):
            return tkt
        html_file = self._find_html_for_ticket(tkt)
        return parse_ticket_html(html_file)

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
