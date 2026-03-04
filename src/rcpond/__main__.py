"""Example main program."""

from rcpond import config, servicenow

the_config = config.Config("/home/jgeddes/.config/rcpond/rcpond.txt")

the_servicenow = servicenow.ServiceNow(the_config.servicenow_token)

tickets = the_servicenow.get_unassigned_tickets()

for tkt in tickets:
    print(tkt)
