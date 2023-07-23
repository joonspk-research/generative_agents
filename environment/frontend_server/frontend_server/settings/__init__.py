###FOR PUSHING STATIC TO AWS 



# from .base import *
# from .production import *

# try:
#   from .local import *
# except:
  # pass






###FOR GENERAL USES





from .base import *

try: 
  from .local import *
  live = False
except:
  live = True

if live:
  from .production import *
