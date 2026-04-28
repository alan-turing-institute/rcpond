"""Demo script for display_response — shows all three response variants without hitting the LLM."""

from rich.console import Console

from rcpond.display import display_response
from rcpond.llm import LLMResponse

console = Console()

# ---------------------------------------------------------------------------
# 1. Freeform note tool call
# ---------------------------------------------------------------------------

console.rule("[bold]1. post_freeform_note[/bold]")

display_response(
    LLMResponse(
        ticket_number="RES0001192",
        llm_model="gpt-4o",
        reasoning=(
            "The request is for an Azure Project subscription renewal. "
            "Credits requested (£1,210) match the 12-month cost breakdown. "
            "PI details and finance code are present. Data sensitivity is Public. "
            "No outstanding queries — I will post an approval note."
        ),
        response_text=(
            "This request is complete and well-justified. " "I will post a freeform approval note to the ticket."
        ),
        planned_tool_call={
            "function": {
                "name": "post_freeform_note",
                "arguments": {
                    "note": (
                        "Thank you for your request. We have reviewed your Azure allocation "
                        "request and it has been approved. Your subscription will be renewed "
                        "shortly. Please contact us if you have any questions."
                    )
                },
            }
        },
    ),
    console=console,
)

# ---------------------------------------------------------------------------
# 2. No tool call
# ---------------------------------------------------------------------------

console.print()
console.print()
console.rule("[bold]2. No tool call[/bold]")

display_response(
    LLMResponse(
        ticket_number="RES0001193",
        llm_model="gpt-4o",
        response_text=(
            "This request is missing a finance code and the PI email address. "
            "I cannot approve it without this information. No action taken."
        ),
    ),
    console=console,
)

# ---------------------------------------------------------------------------
# 3. Templated note tool call
# ---------------------------------------------------------------------------

console.print()
console.print()
console.rule("[bold]3. post_templated_note[/bold]")

display_response(
    LLMResponse(
        ticket_number="RES0001194",
        llm_model="gpt-4o",
        reasoning=(
            "The request is incomplete — the finance code field is blank and no PMU contact "
            "is listed. I should request the missing information using the standard template."
        ),
        response_text=(
            "The request is missing required finance information. "
            "I will send the 'missing_information' template to prompt the requestor."
        ),
        planned_tool_call={
            "function": {
                "name": "post_templated_note",
                "arguments": {
                    "template_name": "request_missing_information.yaml.j2",
                    "missing_fields": "finance code, PMU contact email",
                },
            }
        },
    ),
    console=console,
)
