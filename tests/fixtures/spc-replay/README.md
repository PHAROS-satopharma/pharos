# spc-replay (PHAROS fixture)

Real past versions of one label, replayed through the label watch's change detector (`collectors/spc/replay.py`).
Saved 6 November 2026, 23:36 Cairo.

* `corlanor_v16.xml`: Corlanor (ivabradine), Amgen, DailyMed set id `92018a65-38f6-45f7-91d4-a34921b81d0d`,
  SPL version 16 (published 4 Dec 2018, effectiveTime 2017-01-17). The adult heart-failure label.
* `corlanor_v20.xml`: the same set id, SPL version 20 (published 17 May 2019, effectiveTime 2019-04-22). This
  version adds paediatric patients aged 6 months and older with heart failure due to dilated cardiomyopathy
  (FDA approval, April 2019), changing the indications, dosage, contraindications, warnings and precautions,
  adverse reactions, interactions and specific populations.

Both were read with `https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?type=zip&setid=<set id>&version=<n>`, the
XML file inside the zip. (`/services/v2/spls/<set id>.xml?version=<n>` ignores the version and answers the
current label.) The first read of version 31 came back cut short (a zip without its end), so the replay checks
each zip and asks again.

Versions 31 (Jun 2023) and 33 (Nov 2025) have the same safety sections: the detector finds no change between
them, which is the right answer.
