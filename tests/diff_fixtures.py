MODIFIED_AND_ADDED_PATCH = """diff --git a/app/service.py b/app/service.py
index 1111111..2222222 100644
--- a/app/service.py
+++ b/app/service.py
@@ -10,2 +10,3 @@ class ReportBuilder:
     def build(self):
-        return None
+        result = self._compute()
+        return result
diff --git a/app/helpers.py b/app/helpers.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/app/helpers.py
@@ -0,0 +1,2 @@
+def compute_total(values):
+    return sum(values)
"""

RENAMED_PATCH = """diff --git a/app/old_name.py b/app/new_name.py
similarity index 87%
rename from app/old_name.py
rename to app/new_name.py
index 4444444..5555555 100644
--- a/app/old_name.py
+++ b/app/new_name.py
@@ -1,2 +1,2 @@
 def handler():
-    return 1
+    return 2
"""

DELETED_PATCH = """diff --git a/app/legacy.py b/app/legacy.py
deleted file mode 100644
index 6666666..0000000
--- a/app/legacy.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def obsolete():
-    pass
"""

BROKEN_PATCH = """diff --git a/app/service.py b/app/service.py
@@ -10,7 +10,8 @@
 not a real hunk
"""
