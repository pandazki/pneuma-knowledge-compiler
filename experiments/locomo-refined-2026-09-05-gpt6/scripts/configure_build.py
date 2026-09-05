#!/usr/bin/env python3
"""Material-informed contracts without dataset excerpts or answer values."""
from pathlib import Path
import shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
FAMILIES=[
 [('life-paths','personal development, belonging, education and vocation'),('creative-practices','creative practices and independently evolving works'),('family-life','household activities and relationships')],
 [('ventures','independently developing businesses and their milestones'),('performances','creative collaborations, rehearsals and performances')],
 [('community-work','civic initiatives, campaigns and volunteering'),('activities','fitness and travel activities')],
 [('creative-work','writing projects and other sustained creative work'),('competitions','teams, competitive activities and achievements'),('media','works with a continuing personal history')],
 [('fan-projects','collaborative creative projects and their changing scope'),('sport-careers','teams, roles, training and career milestones'),('collections','personally meaningful collections and objects')],
 [('companions','pets and their distinct life histories'),('career-paths','employment and professional transitions'),('outings','outdoor activities and meaningful places')],
 [('software','independently evolving software and creative projects'),('learning','courses and skill development'),('companions','pets and their distinct histories')],
 [('practice','teaching, professional work and community practice'),('keepsakes','personally meaningful objects and places'),('life-paths','family relationships and personal transitions')],
 [('journeys','travel and shared activities'),('creative-practices','learning and creative development'),('possessions','major objects with a changing ownership or use history')],
 [('journeys','travel, relocation and cultural experiences'),('collaborations','professional and creative collaborations'),('interests','sustained interests and participation')],
]
COMMON='''# Personal conversation memory

Both speakers are independent people. File a statement under its actual subject;
the addressee does not inherit the speaker's experience. Quoted third parties,
pets, organizations and works remain distinct. Do not invent the owner's identity.

## Admission and evidence
Retain concrete experiences, personal preferences, meaningful possessions,
relationships, reasons, goals, commitments, named works and milestones. A small
specific fact can support later recollection even when no decision was made.
Skip greetings, generic encouragement and repeated praise without new information.
Preserve exact names, quantities, places, comparative preferences and reasons.
Distinguish actual events from plans, aspirations, suggestions and hypothetical cases.
For lists, keep the complete explicitly stated membership and who it describes.
An explicit negative or changed preference is useful personal knowledge.

Each text message is the speaker's report. BLIP captions are derived observations;
image-search queries are contextual metadata, not proof of an event or identity.
Keep useful visual descriptions with their provenance. When representations disagree,
preserve the disagreement; do not quietly replace a person's statement with a caption.
Image URLs alone do not constitute direct visual inspection.

## People and time
people/{slug}.md records one person's enduring background, relationships, preferences,
roles and links to their ongoing subjects. Create the two speakers on substantive
appearance; create other people when enough distinguishing information makes a
separate record useful. Do not combine two speakers. Aliases require explicit
identity equivalence, self-identification or repeated unambiguous address; an isolated
co-mention or honorific is insufficient. Take channel identities only from sources.

Every subject page carries dated developments: preserve occurrence time separately
from the reporting session. Anchor relative dates to that session's date and retain
the original expression. Resolve exact dates only when unambiguous. A reported first
mention is not a start date. Preserve beginnings, endings, durations and uncertainty.

Employment, relationships, commitments and ongoing project status can change: retain
prior valid states and supersede them when new evidence reports a transition. Correct
only claims that were already wrong when written. Do not archive ordinary history;
past experiences remain relevant memory.

## Filing and overview
One independently evolving subject earns one page. A one-off detail belongs with its
person or established subject; do not create a page per session or per mention.
Connect a person to their own projects and experiences without duplicating all details.
The definition identifies the subject, summary states the present situation,
introduction preserves origins, and connections explain its relations. Rewrite that
picture when the meaning changes, not merely because one more fact arrived.
Never admit credentials or identity-document numbers.
'''

def main():
 for i,families in enumerate(FAMILIES):
  dest=ROOT/'contracts'/f'conversation-{i+1:02d}.md'
  paths=['people/{slug}.md']+[name+'/{slug}.md' for name,_ in families]
  body='---\nskill_id: lr6r2-memory\nversion: lr6r2-v1\npath_templates:\n'+''.join('  - '+p+'\n' for p in paths)+'---\n'+COMMON
  body+='\n## Subject families for this library\n'
  for name,meaning in families:body+=f'\n- `{name}/{{slug}}.md`: {meaning}. Create a page when it can evolve independently; record its origin, participants, motivations, dated milestones and changing state. Incidental references stay on an existing person or subject page.\n'
  dest.write_text(body)
  app=ROOT/f'app-{i+1:02d}';engine=app/'engine'
  shutil.copy2(dest,engine/'compile/contract.md')
  p=engine/'engine.yaml';s=p.read_text().replace('components: ""','components: "people,time"').replace('people_family: memory/people/{slug}.md','people_family: people/{slug}.md').replace('pricing: ""','pricing: |\n  openrouter:openai/gpt-5.6-luna = 0.20/1.20/0.20/0.20 USD\n  openrouter:openai/text-embedding-3-small = 0.02/0/0.02/0.02 USD')
  p.write_text(s)
  (engine/'compile/challenge.yaml').write_text('enabled: true\nmax_rounds: 1\nmax_questions: 4\nmax_output_tokens: 4096\ncompensate: true\n')
  (engine/'evolve/evolve.yaml').write_text('auto_trigger: false\ntrigger_topic_docs: 1\ntrigger_new_claims: 60\ndraft_ttl_hours: 168\n')
  # Date-only occurrence metadata; UTC is a reproducibility default, not a claimed locale.
  (engine/'persona/profile.yaml').write_text(f'display_name: "Conversation {i+1:02d}"\nlocale:\n  timezone: UTC\n  language: en\nprovenance:\n  timezone: deployment_default\n  language: profile\n  region: unstated\npreferences:\n  response_language: en\n')
  snap=ROOT/'contracts'/f'engine-{i+1:02d}'
  for rel in ['engine.yaml','compile/challenge.yaml','evolve/evolve.yaml','intake/intake.yaml','persona/profile.yaml']:
   target=snap/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(engine/rel,target)
  subprocess.run(['git','-C',str(engine),'add','.'],check=True,stdout=subprocess.DEVNULL)
  subprocess.run(['git','-C',str(engine),'commit','-m','Configure frozen build design'],check=True,stdout=subprocess.DEVNULL)
 print('BUILD CONFIGURATION: 10 contracts and engines')
if __name__=='__main__':main()
