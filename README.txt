Alva Xpress auto-updating catalog
---------------------------------
Files:
  build_site.py   downloads JCM's product list and builds the catalog
  template.html   the catalog design (edit this to change the look)
  update.yml      the daily schedule (goes in .github/workflows/ on GitHub)

The site rebuilds every day at 01:30 Dubai time. You can also run it by hand:
GitHub > Actions > "Update catalog" > Run workflow.
If JCM's feed returns too few products, the update is skipped and the
old catalog stays online.
