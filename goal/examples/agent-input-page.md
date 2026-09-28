::ILANG::v5.0::ENGINEERING_BOOK
[TYPE:engineering_book]
[ID:AGENT-INPUT-PAGE-ACCEPTANCE]
[DATE:2026-09-28]
[LANG:en]

::OBJECTIVE{id:g1|owner:user|trust:trusted|version:2|status:active}
  target: the page Agent Input Authority Mapping is published and the homepage says what iLang is
  ACCEPT: every item of the rubric passes
  NON_GOALS: a new repository, a change to the specification
  DONE_WHEN: goal_check.py returns 0 on this book

::RUBRIC{H1: the homepage shows the sentence that says what iLang is|check:count|url:https://ilang.ai/|pattern:"iLang tells AI what a sentence is allowed to become."}
::RUBRIC{H2: the homepage has the section Why this exists and the section opens as agreed|check:count|url:https://ilang.ai/|regex:"<h2>Why this exists</h2>[\s\S]{0,400}It is compiled judgment\."|expect:1}
::RUBRIC{H3: the homepage does not offer a compression rate as a reason to use iLang|check:human}
::RUBRIC{H4: the structured data and llms.txt do not offer a compression rate as a reason to use iLang|check:human}
::RUBRIC{H5: every JSON-LD block of the homepage parses|check:json|url:https://ilang.ai/|in:jsonld}

::RUBRIC{A1: the page answers at its address|check:status|url:https://research.ilang.ai/protocol/agent-input/|expect:200}
::RUBRIC{A2: the text gives no dimension a value that outside content gets by default|check:human}
::RUBRIC{A3: the text brings in no declaration, dimension, constant or module the specification does not have|check:human}
::RUBRIC{A4: the mapping table has a heading row and one row for each of the nine kinds of attack|check:count|url:https://research.ilang.ai/protocol/agent-input/|regex:"<tr[ >]"|expect:10}
::RUBRIC{A5: every link to another site answers, or answers 403 because the site turns programs away|check:links|url:https://research.ilang.ai/protocol/agent-input/|allow:403}
::RUBRIC{A6a: the W3C checker answers with its list of messages|check:count|url:"https://validator.w3.org/nu/?doc=https%3A%2F%2Fresearch.ilang.ai%2Fprotocol%2Fagent-input%2F&out=json"|regex:"\"messages\"\s*:\s*\["|expect:1}
::RUBRIC{A6: the list of the W3C checker holds no error|check:count|url:"https://validator.w3.org/nu/?doc=https%3A%2F%2Fresearch.ilang.ai%2Fprotocol%2Fagent-input%2F&out=json"|regex:"\"type\"\s*:\s*\"error\""|expect:0}
::RUBRIC{A7: the structured data passes the Rich Results Test of Google|check:human}
::RUBRIC{A8: the sitemap lists the page|check:count|url:https://research.ilang.ai/sitemap.xml|pattern:"https://research.ilang.ai/protocol/agent-input/"}
::RUBRIC{A9: the text a reader sees has no Chinese character and no dash used as punctuation|check:count|url:https://research.ilang.ai/protocol/agent-input/|in:text|regex:"[\u4e00-\u9fff\u2013\u2014]"|expect:0}
::RUBRIC{A10: the homepage links to the page|check:count|url:https://ilang.ai/|pattern:"https://research.ilang.ai/protocol/agent-input/"}
