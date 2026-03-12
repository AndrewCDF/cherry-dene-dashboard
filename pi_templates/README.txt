Cherry Dene Farm Pi Deployment Templates

Files:
- controller_config.template.json
- controllers.template.json

Use on each shed Pi:
1. Copy shed_controller_server.py onto the shed Pi.
2. Copy controller_config.template.json to:
   controller_data/controller_config.json
3. Change:
   - shed_no
   - dashboard_url
   - serial_port if needed

Example:
- Shed 1 Pi uses shed_no 1
- Shed 4 Pi uses shed_no 4

Use on the office Pi:
1. Copy dashboard_server.py onto the office Pi.
2. Copy controllers.template.json to:
   data/controllers.json
3. Replace each sync_url with the actual IP address of that shed Pi.

How sync works:
- Shed Pi 4 pushes to /api/shed/4/sync on the office dashboard
- Office edits for Shed 4 push back to the URL listed under key "4"
- Each shed only syncs its own corresponding shed entry
