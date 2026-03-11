"""Example main program."""

from rcpond import config, servicenow

the_config = config.Config(".env")

the_servicenow = servicenow.ServiceNow(the_config)

tickets = the_servicenow.get_unassigned_tickets()

for tkt in tickets:
    print(tkt)
    print()
