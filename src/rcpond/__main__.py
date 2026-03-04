"""Example main program.

"""

import config, servicenow

the_config = config.Config("~/.config/rcpond.txt")

the_servicenow = servicenow.ServiceNow(the_config.
