with open('alpha_bot.py', 'r') as f:
    content = f.read()

content = content.replace("def log_simulation(expression, settings, result):", "def log_simulation(expression, settings, result, item=None):")
content = content.replace("def save_submittable(expression, settings, result):", "def save_submittable(expression, settings, result, item=None):")

content = content.replace("""        entry = {
            "timestamp": time.time(),
            "expression": expression,
            "settings": settings,
            "sharpe": result.get('sharpe', 0) if result else None,""", """        entry = {
            "timestamp": time.time(),
            "expression": expression,
            "settings": settings,
            "source": item.get('source', 'unknown') if item else 'unknown',
            "template_name": item.get('template_name', '?') if item else '?',
            "sharpe": result.get('sharpe', 0) if result else None,""")

content = content.replace("""        entry = {
            "timestamp": time.time(),
            "expression": expression,
            "settings": settings,
            "sharpe": result.get('sharpe', 0),""", """        entry = {
            "timestamp": time.time(),
            "expression": expression,
            "settings": settings,
            "source": item.get('source', 'unknown') if item else 'unknown',
            "template_name": item.get('template_name', '?') if item else '?',
            "sharpe": result.get('sharpe', 0),""")

content = content.replace("log_simulation(expression, settings, res)", "log_simulation(expression, settings, res, item)")
content = content.replace("log_simulation(neg_expr, settings, neg_res)", "log_simulation(neg_expr, settings, neg_res, item)")
content = content.replace("save_submittable(expression, settings, res)", "save_submittable(expression, settings, res, item)")

with open('alpha_bot.py', 'w') as f:
    f.write(content)
