Cherry Dene Farm Pi Deployment Templates

Files:
- controller_config.template.json
- controllers.template.json
- farm_setup.template.json
- shed_setup.template.json

Use on each shed Pi:
1. Copy shed_controller_server.py onto the shed Pi.
2. Copy controller_config.template.json to:
   controller_data/controller_config.json
3. Change:
   - shed_no
   - dashboard_url
   - sync_token
   - serial_port if needed

Example:
- Shed 1 Pi uses shed_no 1
- Shed 4 Pi uses shed_no 4

Planning all sheds:
1. Fill out shed_setup.template.json first.
2. Use that file as the master list for:
   - each shed Pi IP
   - which augers are fitted
   - the auger labels for that shed
3. Then copy the matching values into each shed's:
   controller_data/controller_config.json

Master planning file:
1. Fill out farm_setup.template.json if you want one file covering:
   - office dashboard
   - all sheds
   - the bore hole controller
2. Use that as the farm-wide planning document.
3. Then derive:
   - each shed's controller_config.json
   - the office data/controllers.json
   - the bore hole controller entry in office data/controllers.json

Use on the office Pi:
1. Copy dashboard_server.py onto the office Pi.
2. Copy controllers.template.json to:
   data/controllers.json
3. Replace each sync_url with the actual IP address of that shed Pi.
4. Add the bore hole controller to the same file under key "borehole".
5. Set the same shared sync_token on the office and controller configs so office/controller sync and backup collection are authenticated.

How sync works:
- Shed Pi 4 pushes to /api/shed/4/sync on the office dashboard
- Office edits for Shed 4 push back to the URL listed under key "4"
- Each shed only syncs its own corresponding shed entry
- The bore hole controller also lives in data/controllers.json under key "borehole"
  for office-side backup collection and controller status tracking

Note:
- The bore hole uses its own simpler dashboard, but it is still treated as a controller-class device in office configuration and backups.
