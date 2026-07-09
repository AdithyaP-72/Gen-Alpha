import json
import numpy as np
import matplotlib.pyplot as plt
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, r2_score, mean_squared_error

# Load data
history = []
with open('simulation_history.json') as f:
    for line in f:
        if line.strip():
            history.append(json.loads(line))

print(f"Loaded {len(history)} simulations.")

# Feature extraction (similar to train_recommender.py)
X_class = []
y_class = []
X_reg = []
y_reg = []

def extract_features(expr, settings):
    # simple proxy features
    length = len(expr)
    has_ts = 1 if 'ts_' in expr else 0
    has_group = 1 if 'group_' in expr else 0
    decay = settings.get('decay', 5)
    truncation = settings.get('truncation', 0.08)
    neut_map = {'NONE': 0, 'SECTOR': 1, 'INDUSTRY': 2, 'SUBINDUSTRY': 3, 'MARKET': 4}
    neut = neut_map.get(settings.get('neutralization', 'SUBINDUSTRY'), 3)
    return [length, has_ts, has_group, decay, truncation, neut]

for h in history:
    expr = h.get('expression', '')
    settings = h.get('settings', {})
    fit = h.get('fitness', 0) or 0
    
    if expr:
        feats = extract_features(expr, settings)
        is_success = 1 if fit >= 1.0 else 0
        X_class.append(feats)
        y_class.append(is_success)
        
        X_reg.append(feats)
        y_reg.append(fit)

X_class = np.array(X_class)
y_class = np.array(y_class)
X_reg = np.array(X_reg)
y_reg = np.array(y_reg)

# Train Classifier
X_train, X_test, y_train, y_test = train_test_split(X_class, y_class, test_size=0.2, random_state=42)
clf = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)
clf.fit(X_train, y_train)

y_pred = clf.predict(X_test)
print("\nClassification Report:")
print(classification_report(y_test, y_pred))

# Confusion Matrix Plot
cm = confusion_matrix(y_test, y_pred)
fig, ax = plt.subplots(figsize=(6, 4))
cax = ax.matshow(cm, cmap=plt.cm.Blues)
fig.colorbar(cax)
for (i, j), z in np.ndenumerate(cm):
    ax.text(j, i, '{:d}'.format(z), ha='center', va='center', bbox=dict(boxstyle='round', facecolor='white', edgecolor='0.3'))
plt.title('Gradient Boosting Confusion Matrix')
plt.ylabel('True Label')
plt.xlabel('Predicted Label')
plt.savefig('pics2/confusion_matrix.png')

# Feature Importance Plot
importances = clf.feature_importances_
features = ['Expression Length', 'Has TS_', 'Has Group_', 'Decay', 'Truncation', 'Neutralization']
plt.figure(figsize=(8,5))
y_pos = np.arange(len(features))
plt.barh(y_pos, importances, align='center')
plt.yticks(y_pos, features)
plt.title('Feature Importances (Gradient Boosting)')
plt.savefig('pics2/feature_importance.png')

print("Saved plots to pics2/")
