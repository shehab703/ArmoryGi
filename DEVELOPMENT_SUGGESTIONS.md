# خارطة طريق التطوير — ArmoryGIS Pro

> وثيقة داخلية للمطوّر. كل ملاحظة هنا مبنية على فحص فعلي للمستودع على فرع
> `arena/01a045d4-armorygi` (الأرقام أسفله مُولّدة من المستودع، لا تقديرية).

---

## 0) ملخّص تنفيذي

| # | الخلاصة | الأثر |
|---|---|---|
| 1 | التطبيق **يعتمد على CDN أثناء التشغيل** في مواضع العرض ثلاثي الأبعاد، وهذا يناقض التصميم "Offline-First" المعلن في `README.md`. إصلاح واحد أُنجز اليوم، وبقي المسار في `views/single_weapon_view.py` يعمل بـ fallback صحيح لكنه يظل يعتمد على الشبكة إن غاب الملف المحلّي. | حرج |
| 2 | **لا يوجد CI** (`/.github` غير موجود) و`build.sh` يُكمل البناء حتى لو فشلت الاختبارات. طبقة الاختبار 445 سطر مقابل 18,902 سطر (~2.4%). | حرج |
| 3 | المستودع يتتبّع مخرجات تشغيلية (`.db` / `.sql` / صور اختبار) وقطع تجميع `pyproject.toml` غير متسقة مع reality → التوزيع بالعجلة (wheel) لا ينتج شيئاً. | متوسط |

---

## 1) ما نُفِّذ في هذه الجولة (مرجعية للـ PR)

| الملف | التغيير | حالة الفحص |
|---|---|---|
| `views/weapon_3d_view.py` | معرض 2D بعرض كامل داخل تبويب العرض: وضعان (3D / 2D) في تبويب واحد، تنقّل بالسحب (ماوس/لمس/تتبّع) + أزرار + شريط مصغّرات + لوحة مفاتيح، تكبير عند المؤشّر مع تقييد الانزياح، عرض تلقائي، وضع ملء الشاشة، سحب وإفلات للصور، تعيين صورة رئيسية مع حفظها في قاعدة البيانات | 31 اختباراً headless أخضر (`tests/test_weapon_3d_gallery.py` + اختبارات قاعدة البيانات) + فحصا تكامل: بناء `Weapon3DView` والإيماءات الفعلية عبر `QTest`، و`MainWindow` كاملاً على منصة `offscreen` |
| `views/weapon_3d_view.py` | **إصلاح offline**: صفحة `model-viewer` كانت تحمّل السكربت من `https://unpkg.com/...` فقط؛ الآن تُفضَّل النسخة المرفقة `resources/html/Js/model-viewer.min.js` مع بقاء الـ CDN كخطة بديلة | تأكيد يدني على المسارين |
| `database/db_manager.py` | **إصلاح عطل فعلي** في `add_weapon`: كان مفتاح `category`/`country` (نص) يبقى في القاموس إذا لم يوجد صف مطابق، فيُرمى `AttributeError: 'str' object has no attribute '_sa_instance_state'` خارج `SQLAlchemyError` ولا تلتقطه المعالجة. الآن تُحلّ روابط الفهرسة الأربعة (`category`, `country`, `guidance`, `propulsion`) بأسلوب get-or-create وتُحذف مفاتيح النصوص دائماً | `tests/test_database.py` كان يفشل وأصبح أخضر |
| `database/db_manager.py` | **إصلاح عطل ثانٍ بالرصد نفسه:** معالج `except Exception` في `add_weapon_model` كان يعيد `(added, skipped)` — متغيّرين يخصّان `add_weapon_images_batch` — فيرفـع `NameError` بدل الإبلاغ عن الفشل (و`views/dashboard_view.py:590` يتوقّع `bool`). أُصلح إلى `return False` مع رسالة Log صحيحة | اختبار انحدار: `test_add_weapon_model_error_path_returns_false` |
| `views/weapon_3d_view.py` | معرض 2D لا يكتب في `~/.armorygis` أثناء الاختبار (عزل `GALLERY_ROOT` في `tests/test_weapon_3d_gallery.py`)، وسجلّ `logger` بدل `except Exception: pass` الصامت | |
| `tests/conftest.py` | كان يستورد `database.schema` (**غير موجود** — الملف الوحيد هو `database/schema.sql`) → كل الاختبارات كانت تسقط عند التجميع. صُحّح الاستيراد إلى `database.db_manager.Base` وأُضيف إدخال جذر المستودع إلى `sys.path` | `python -m pytest tests/ -q` يعمل مباشرة من الجذر |
| `pyproject.toml` | `addopts` كان يمرّر `--cov=armorygis` لحزمة غير موجودة وبدون `pytest-cov` في `dev` → `pytest` يفشل فوراً. أُزيل، وأُضيفت `pythonpath=["."]` و`[tool.coverage.*]` و`pytest-cov`. نسخة المشروع صارت `2.0.0` (كانت `1.0.0` بينما `build.sh` تقول `2.0.0`)، و`requires-python` صار `>=3.10` (كان `>=3.9` لكن `views/main_window.py:85` و`views/map_view.py:110,160,242,360` و`views/weapon_detail_view.py:32` تستخدم PEP 604 (`X \| None`) بدون `from __future__ import annotations` → تنكسر على 3.9). فُحص `mypy` تدريجي عبر `[[tool.mypy.overrides]]` بدل تعطيله | `tomllib` يقرأ الملف، و`pytest` أخضر |

**ما لم يُنفَّذ** (رُصد وتوثيق فقط): نقل `resources/` إلى داخل الحزمة، تقسيم `weapon_3d_view.py`، Alembic، تنظيف تاريخ Git، وربط/حذف تبويب المحاكيات الفارغ.

---

## 2) الأرقام الحالية

```text
ملفات Python            68
أسطر Python             18,957
except Exception          146   (منها ~39 متبوعة بـ pass صامت)
أسطر الاختبارات             481    (5 ملفات، 31 اختباراً أخضر)
أكبر الملفات:
  views/weapon_3d_view.py      1,596   ← أكبر ملف في المستودع بعد إضافة المعرض
  database/db_manager.py       1,553
  views/main_window.py         1,448
  views/report_workspace_view.py 1,363
حجم resources/                ~28 MB
ملفات تشغيلية متتبَّعة في Git: armory_backup.db (299 KB), armory_export.db (299 KB), armory_export.sql (186 KB),
                             tests/*.png + tests/*.pdf (أصول اختبار مبعثرة)
```

---

## 3) P0 — أُغلق اليوم أو يجب أن يُغلق هذا الأسبوع

### 3.1 CI غير موجود ✅ مقترح جاهز
لا `.github/workflows`. أضِف ملفاً واحداً يشغّل الاختبارات headless على Linux ويبني نسخة Windows:

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push: {branches: [main]}
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - name: System deps (Qt offscreen)
        run: |
          sudo apt-get update
          sudo apt-get install -y libgl1 libegl1 libxkbcommon0 libdbus-1-3 \
            libfontconfig1 libnss3 libxcomposite1 libxdamage1 libgbm1
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt pytest pytest-qt pytest-cov
      - name: Tests
        env:
          QT_QPA_PLATFORM: offscreen
          QTWEBENGINE_DISABLE_SANDBOX: "1"
          ARMORYGIS_DATA_DIR: ${{ github.workspace }}/.armorygis-ci
        run: python -m pytest tests/ -q
  windows-build:
    needs: test
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt pyinstaller
      - run: bash build.sh || true          # إلى أن يصير فشل الاختبار قاطعاً
        env: {ARMORYGIS_CI: "1"}
      - uses: actions/upload-artifact@v4
        with: {name: armorygis-windows, path: dist/}
```

وبعد استقراره: احذف `|| log_warn "Tests failed, continuing build..."` من `build.sh:run_tests`
(السطر الذي يجعل فشل الاختبار غير قاطع في البناء).

### 3.2 لا شيء في المستودع يجب أن يتتبّع مخرجات تشغيل
```bash
git rm --cached armory_backup.db armory_export.db armory_export.sql
git rm --cached tests/*.png tests/*.pdf          # انقلها إلى tests/fixtures/
printf '%s\n' '*.db' '*.sql' 'exports/' 'tests/fixtures/_out/' >> .gitignore
```
إن أردت تقليص حجم التاريخ لاحقاً (`.git` الحالي ~14 MB):
```bash
git filter-repo --invert-paths --path armory_backup.db --path armory_export.db --path armory_export.sql
```
> **ملاحظة أمنية:** قبل أي تنقية للتاريخ، تأكّد أن هذه الملفات لا تحتوي بيانات حقيقية حسّاسة؛ إن احتوت عليها فالتاريخ المُعاد كتابته يجب أن يُدفَع قسراً مع إبطال/تدوير أي محتوى حسّاس، ولا يكفي حذف الملفات من HEAD.

### 3.3 `resources` غير قابلة للتوزيع مع الـ wheel
`[tool.setuptools.packages.find] include = ["armorygis*"]` — لا توجد حزمة بهذا الاسم أصلاً؛ البنية مسطّحة
(`views/`, `utils/`, `database/`, …). النتيجة: `pip install .` ينصب شيئاً لا يعمل، و`resources/html/**` لن يُنقل أبداً.
خياران، لا ثالث لهما:
1. **التوزيع بالتجميع فقط (موصى به قصيراً):** احذف `[project.scripts]` و`[tool.setuptools.packages.*]`، وصرّح أن `pyproject.toml` للتنمية/الفحص فقط، ووزّع عبر PyInstaller (`packaging/pyinstaller.spec`) مع إضافة `--add-data "resources;resources"` (تحقّق أن الـ spec يفعله).
2. **حزمة حقيقية (متوسّط المدى):** انقل الكود إلى `armorygis/` ثم:
   ```toml
   [tool.setuptools.packages.find]
   include = ["armorygis*"]
   [tool.setuptools.package-data]
   armorygis = ["resources/**/*", "database/schema.sql"]
   ```
   هذا يستبدل مسارات `Path(__file__).resolve().parents[1] / "resources"` (موجودة في `views/single_weapon_view.py:803`
   و`views/weapon_3d_view.py` في `_model_viewer_script_src`) بدالة `resources_root()` واحدة في `config.py`.

### 3.4 `GALLERY_ROOT` باسم مكسور
`utils/weapon_media_library.py:12`:
```python
GALLERY_ROOT = APP_DATA_DIR / "weapouns_gallaries"   # "weapons galleries"
```
اسم المجلد ظاهر للمستخدم (يُفتح من زر «مجلد الوسائط») و`.gitignore` يتضمّن قاعدة `GALLARIES/` ميتة لا تطابقه.
إصلاح بمهلة ترحيل:
```python
GALLERY_ROOT = APP_DATA_DIR / "weapons_galleries"
LEGACY_GALLERY_ROOT = APP_DATA_DIR / "weapouns_gallaries"   # اتركه للقراءة فقط + ترحيل عند أول تشغيل
```
ونفس الشيء لقاعدة `sim sess/` في `.gitignore` (اسم بمسافة وسطى، لا يطابق أي مسار).

### 3.5 فهرسة التبويبات مكتوبة يدوياً
`views/main_window.py:94` و`:351` يضبطان `_weapon_3d_tab_index = 7`، و`:1423` يستدعي
`self.main_tabs.setTabText(7, ...)` — أي إضافة/إزالة تبويب تُبدّل معنى الرقم بصمت.
استبدل بحقل واحد:
```python
self._weapon_3d_tab_index = self.main_tabs.addTab(self._weapon_3d_view, icon, "3D Viewer")
```
وامنع الأرقام السحرية بمنصة اختبار تفرض أن `tabText(i)` يطابق ما تتوقعه الترجمة.

---

## 4) P1 — المتانة وصحة البيانات

| # | البند | أين | حجم |
|---|---|---|---|
| 4.1 | سياسة استثناء واحدة: لا `except Exception: pass`. اجعلها `logger.warning(..., exc_info=True)` + حالة مستخدم واضحة. ابدأ من الملفات الأكثر (146 موضعاً، منها ~39 صامتة) | `views/*.py`, `database/db_manager.py` | M |
| 4.2 | `utils/tile_cache.py:273` معلّق صراحة: `# This is a placeholder - actual implementation requires db_manager import` → كاش بلاط يعمل بدون طبقة تخزين؟ أكمل أو احذف المسار ووثّق السلوك | `utils/tile_cache.py` | S |
| 4.3 | **مخططات قاعدة البيانات بلا Alembic**: `requirements.txt` يطلب `alembic>=1.12.1` لكن لا `alembic.ini` ولا `migrations/`. أي تغيير عمود حالياً يعتمد على `Base.metadata.create_all` فقط → ترقيات المستخدمين تنكسر. أضِف تهيئة Alembic + أول migration يطابق `database/schema.sql`، واختباراً في CI يفعل `alembic upgrade head` على نسخة مُصدَّرة | `database/` | M |
| 4.4 | مفاتيح `QSettings` بلا مساحة اسمية (`media/gallery_2d_extensions`)، وتُقرأ في 3 مواضع. موحّدها في `utils/settings_schema.py` (مفاتيح + أنواع + قيم افتراضية) ووثّقها | `utils/`, `views/` | S |
| 4.5 | التبويبات الثقيلة تُنشأ كـ `QWidget()` فاضية (`views/main_window.py:307,336,354,360`) ثم تُستبدل عند أول فتح — منطق مكرّر 4 مرات. استخرِج `utils/lazy_tab.py: LazyTab(Loadable)` يحمل مرة واحدة، ويشغّل `pre_cache_worker` للسخن | `views/main_window.py` | M |
| 4.6 | `views/__init__.py` يستورد `MainWindow` → أي استيراد لملف عرض واحد يجرّ `QtWebEngine` وكل الواجهة. هذا جعل اختبار وحدة بسيط يتطلب WebEngine (وثبّتناه بـ `pytest.importorskip` اليوم). اجعل `views/__init__.py` فارغاً واستورد بمساره الكامل | `views/` | S |
| 4.7 | `models/weapon_model.py:44` يستنتج المفتاح من عنوان العمود بإزاحة نصوص (`replace("(m)","m")`) — كسر فوري عند تغيير عنوان. استخدم صفاً واحداً من `(header, key)` بدل الاشتقاق | `models/weapon_model.py` | S |
| 4.8 | `requires-python = ">=3.10"` الآن صادق، لكنه يعتمد على عدم انزلاق PEP 604 في ملفات بلا `from __future__ import annotations`. أضِف `ruff` بقاعدة `TID251`/`I001` + `from __future__` إلزامياً في قالب الملفات، أو ارفع المتطلب إلى 3.11 | `pyproject.toml` | S |
| 4.9 | **لا يوجد Linter مفعّل.** قياس اليوم بـ `ruff`: الملفات الجديدة (`views/weapon_3d_view.py` + الاختبارات) = 36 ملاحظة كلها أنماط (`UP006/UP0045/I001/BLE001`) و**صفر** من نوع `F`/`E9`، بينما `views/main_window.py` + `database/db_manager.py` = 188 ملاحظة (أغلبها أسطر CSS طويلة). ابدأ ببوابة ضيّقة: `select = ["F", "E9", "RUF100", "I001"]` على `views/` فقط، ثم وسّع | `pyproject.toml` | S |

---

## 5) P2 — الأداء (مباشرة على تجربة المستخدم)

1. **فكّ ترميز الصور على خيط العمل:** `QPixmap(path)` الكامل في `views/single_weapon_view.py` كان يجمّد الواجهة مع صور 8K.
   المعرض الجديد في `views/weapon_3d_view.py` يستخدم `load_scaled_pixmap()` عبر `QImageReader.setScaledSize`
   (سقف 4096) + إعادة استخدام الصورة الحالية أثناء السحب. **الخطوة التالية:** انقل نفس الدالة إلى
   `utils/media_gallery.py` واستخدمها في `single_weapon_view` و`dashboard_view` أيضاً.
2. **كاش مصغّرات على القرص:** شريط المصغّرات يفكّ ترميز كل صورة عند كل تحميل سلاح.
   `~/.armorygis/cache/thumbs/<sha1(path|mtime)>_256.png` مع `QThreadPool` + `QRunnable` (النمط موجود في `views/pre_cache_worker.py`).
3. **فكّ متزامن للصور الكبيرة في قاعدة البيانات:** `utils/image_utils.py::generate_thumbnail` يستخدم PIL على خيط الواجهة.
   وحّده مع كاش القرص في نقطة واحدة بدل ملفين متوازيين.
4. **الصور داخل تقارير PDF:** تأكد أن `utils/weapon_reports.py` يستخدم المصغّرة لا الأصل (ملفات 8K = تقرير بطيء/حجم هائل).
5. **WebEngine:** كل تبويب ثقيل يبني `QWebEngineView` خاصاً به. معرض 2D الجديد **لا يستخدم WebEngine إطلاقاً**
   (ارسم على `QWidget` مباشرة) — هذا هو الاتجاه لبقية الشاشات النصية/الصور: احتفظ بـ Chromium للنماذج ثلاثية الأبعاد فقط.

---

## 6) P3 — تجربة المستخدم والوصولية

- **لوحة مفاتيح المعرض الحالي** (وثّقها في شريط المساعدة داخل التطبيق): `←/→` (معكوسة في العربية)، `Home/End`،
  `+/-/0`، `مسافة` عرض تلقائي، `F` ملء الشاشة، `P` صورة رئيسية، `Esc` خروج. أضِف نفس الاختصارات إلى `single_weapon_view`.
- **سحب وإفلات** الصور الآن يعمل داخل المعرض؛وسّعها إلى قائمة السلاح وشريط الحالة في `dashboard_view`.
- **وصولية:** كل أزرار المعرض تحتاج `setAccessibleName()` (يوجد `QToolButton` نصّي فقط) وحلقة تركيز مرئية
  (`:focus{outline:2px solid #58a8ff;}` في الثيم العام). حساب التباين الفعلي (WCAG):
  | نص | خلفية | نسبة | AA (4.5) |
  |---|---|---|---|
  | `#7aa8d4` | `#081221` | **7.49** | ✅ |
  | `#4a7099` (نص الحالة/ال placeholder في `weapon_3d_view`) | `#060e1a` | **3.75** | ❌ (مقبول للعناوين الكبيرة فقط) |
  | `#41617f` (أزرار معطّلة) | `#0d1a2b` | **2.70** | مستثنى (معطّل) لكن يُفضَّل 3.0 |
  أي: النص الأساسي سليم، والمشكلة في نصوص الحالة/الإرشاد الداكنة.
- **الوضع الليلي/النهاري:** كل ألوان المعرض مكتوبة يدوياً داخل `setStyleSheet`. انقلها إلى `utils/theme_manager.py` كي لا تنفجر عند إضافة فاتح.
- **RTL:** المعرض يعكس اتجاه الأسهم والسحب تلقائياً عبر `lang_manager.is_arabic()`. نفس المنطق غائب عن شريط الصور في `single_weapon_view.py` (أزرار ثابتة `◀/▶`).
- **مقارنة صورتين جنباً إلى جنب** (مفيد لتقارير الذكاء): زر «قارن» في شريط المصغّرات يعرض الصورة المحددة + الحالية (نفس محرّك الرسم، `QHBoxLayout` من مرحلتين).

---

## 7) P4 — معمارية: مكانٌ واحد للمنطق

`collect_gallery_images()` و`load_scaled_pixmap()` مكتوبتان حالياً داخل `views/weapon_3d_view.py`.
هذا صحيح مؤقتاً (تجنّباً لمس 4 شاشات في دفعة واحدة)، لكنه يجب أن ينتقل إلى:

```text
utils/media_gallery.py
  ├─ collect_gallery_images(weapon, allowed_exts) -> list[str]      # نفس الدالة، بلا Qt
  ├─ load_scaled_pixmap(path, max_side) -> QPixmap|None
  ├─ stage_and_register(db, weapon, paths) -> list[str]            # دمج منطق dashboard_view:544 + weapon_detail_view:170
  └─ class MediaGallery:  index, paths, next(), prev(), go_to(), set_primary()   # بلا Qt ← قابل للاختبار
```
وبعدها يُعاد استخدام `MediaGallery` في `single_weapon_view.py` (شريط صور مكرّر ~120 سطراً) وفي `weapon_detail_view.py`،
ويصبح اختبار التنقل/RTL بلا أي `QApplication`:

```python
def test_rtl_next_wraps():
    g = MediaGallery(["a", "b", "c"], rtl=True)
    g.next(); g.next(); g.next()
    assert g.index == 0
```

وبالمثل `views/weapon_3d_view.py` (1,596 سطراً) ينفجر: قسّمه إلى
`views/weapon_3d_tab/{mode_header,model3d_page,gallery_page,gallery_stage}.py`، أو على الأقل
`_gallery_stage.py` + `_gallery_panel.py` + `weapon_3d_view.py` (واجهة التبويب فقط).

---

## 8) P5 — طبقة الذكاء والتحليل

| # | فكرة | مبرّر من الكود الحالي |
|---|---|---|
| 8.1 | **محرّك تقييم قابل للاختبار:** `utils/intelligence_engine.py` يخلط الحساب مع التنسيق النصي. افصل `score(weapon) -> ProfileScores` (نقي) عن العرض، ثم غطِّه بجدول حقائق (`tests/golden/profiles.json`) | لا يوجد أي اختبار لملفات utils بخلاف `exporters` |
| 8.2 | **محاكي المدى** لا يزال `QWidget()` فاضياً (`views/main_window.py:336`) بينما `views/simulator_view.py` (705 أسطراً) موجود ويُبنى في مكان آخر — اربطه أو احذف أحدهما | تكرار/موت |
| 8.3 | **مقارنة المدى** (`views/range_compare_tab.py`) تستخدم نفس هندسة الحلقة في `database/db_manager.py::get_range_ring_coords` — انسخها إلى `utils/geo_bearing.py` ووحّدها لتجنّب اختلاف التكبير | مصدر واحد للحقيقة |
| 8.4 | **Favorites/SWOT → تصدير:** لوحة SWOT (`swot_analysis_view.py`, 1,042 سطراً) تحرّر نصاً بلا حفظ منسّق؛ أضِف تصدير Markdown/DOCX عبر `utils/exporters.py` الموجود | قيمة سريعة |
| 8.5 | **توسيع الوسائط:** بعد معرض 2D، أضِف «صورة ظلية/بروفايل جانبي» مولّدة من نموذج STL عبر `trimesh` (في `requirements.txt` فعلاً) لعرض تلقائي حتى بدون صور | يقلّل السلاح بلا وسائط |

---

## 9) خطة تنفيذ مقترحة (3 مراحل)

**المرحلة 1 — أسبوع (إطفاء حرائق، مخاطرة صفرية)**
- [ ] `ci.yml` أعلاه + جعل فشل الاختبار قاطعاً في `build.sh`
- [ ] `git rm --cached` للمخرجات التشغيلية + تحديث `.gitignore` (مع `weapons_galleries`)
- [ ] Alembic تهيئة + migration أول + اختبار ترقية
- [ ] إصلاح `GALLERY_ROOT` مع ترحيل، و`addTab` بدل الفهارس السحرية

**المرحلة 2 — أسبوعان (بنية)**
- [ ] `utils/media_gallery.py` + `MediaGallery` النقي، ونقل 4 شاشات إليه
- [ ] تقسيم `views/weapon_3d_view.py` و`empty views/__init__.py`
- [ ] `utils/lazy_tab.py` للتبويبات الأربعة
- [ ] سياسة استثناء موحّدة (146 موضعاً) + `ruff` في CI

**المرحلة 3 — شهر (ميزات)**
- [ ] محرك تقييم نقي + golden tests
- [ ] ربط/حذف المحاكمي، توحيد حلقات المدى
- [ ] كاش المصغّرات على القرص + تصغير الصور في التقارير
- [ ] حزمة `armorygis/` حقيقية أو توزيع PyInstaller فقط (قرار 3.3)

### مؤشرات نجاح مقاسة
| مؤشر | اليوم | هدف |
|---|---|---|
| أسطر الاختبارات / الكود | 2.5% (481/18,957) | ≥ 35% على `utils` + `database` |
| CI | 0 workflow | اختباران + بناء Windows على كل PR |
| `except Exception` بلا تسجيل | ~39 | 0 |
| ملفات تشغيلية في Git | 3 قواعد بيانات/SQL + 6 أصول | 0 |
| تبويبات فارغة في الواجهة | 4 | 0 |
| زمن أول رسم للمعرض | — | < 150 ms لكل صورة ≤ 12 MP |

---

## 10) ملاحظات تشغيلية/أمنية (بما أن المشروع "Defense Use Only")

- `pyproject.toml` يعلن `license = "Proprietary - Defense Use Only"` لكن **لا يوجد ملف `LICENSE`** في المستودع.
  أضِف `LICENSE` + سطر حقوق أعلى كل ملف (أو `LICENSE.md` + مرجع في README) وإلا فالترخيص غير قابل للإنفاذ.
- لا يوجد `CODEOWNERS` ولا نموذج PR/Issue: مستودع دفاعي بلا مراجعة إلزامية = ثغرة عملية. أضِف
  `.github/CODEOWNERS` + `require_reviews: 1` على `main` عبر GitHub (وليس عبر الملفات).
- `utils/ai_service.py` / `utils/ollama_client.py`: تأكّد من (أ) وجود مهلة زمنية لكل طلب، (ب) عدم إرسال أي حقل
  `notes` خارج الشبكة في الوضع «العسكري» (فكّر في `ALLOW_REMOTE_AI=false` افتراضياً)، (ج) توثيق أن أي اتصال
  بـ Ollama محلي فقط ما لم يضبط المستخدم عنواناً.
- `database/schema.sql` + `seed_data.py` لا يُصدران نسخة احتياطية آمنة: إن استُخدم `armory_backup.db` في الميدان،
  فهو الآن منسوخ داخل Git (انظر 3.2) — احذفه وأضِف مجلد نسخ احتياطي مشفّراً/محلياً.
- أصول اختبار باسم سلاح حقيقي (`tests/AGM-158A JASSM - cruise missile.pdf/png`) — راجع سياسياً قبل النشر العلني.

---

## 11) قائمة تحقق قبل كل PR

- [ ] `python -m pytest tests/ -q` (من جذر المستودع، بدون أي `addopts` يدوي)
- [ ] `python -m py_compile $(git ls-files '*.py')`
- [ ] تشغيل الواجهة فعلياً مرة بالعربية ومرة بالإنجليزية (اتجاه السحب/الأسهم في المعرض)
- [ ] لا `print()`، لا `except Exception: pass` جديد
- [ ] لا ملفات تشغيلية (`*.db`, `*.sql`, صور) داخل الـ commit
- [ ] أي نص جديد مُرّ عبر `lang_manager.tr()` أو مُوسوم صراحة كـ «غير مترجم»
