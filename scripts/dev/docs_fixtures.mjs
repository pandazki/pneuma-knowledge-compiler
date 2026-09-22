/** Entirely invented documentation data. No home directory, credentials, or backend reads. */
export const TENANT = 'docs-demo';
export function fixtures(locale) {
  const zh = locale === 'zh';
  const pick = (en, cn) => zh ? cn : en;
  const sourceId = 'demo-planning-meeting';
  const title = pick('Harbor Notes', '港湾笔记');
  const statements = [
    pick('Harbor Notes is a small research notebook that keeps each conclusion beside its source.', '港湾笔记是一个小型研究笔记工具，每条结论都保留对应的原始材料。'),
    pick('The first pilot will support local Markdown import and source-linked answers. Team sharing is outside this pilot.', '首轮试用支持本地 Markdown 导入和带来源的问答；团队共享不在本轮范围内。'),
    pick('The next review is September 28. A public release has not been approved.', '下一次评审安排在 9 月 28 日，尚未批准公开发布。'),
    pick('When a conclusion changes, keep the earlier claim and cite the new evidence.', '结论变化时保留原有主张，并为新结论附上新的证据。'),
  ];
  const specs = [
    ['harbor-overview', 'projects/harbor-notes/overview.md', title, 'project', [0, 1, 2]],
    ['harbor-import', 'projects/harbor-notes/features/import.md', pick('Local document import', '本地文档导入'), 'feature', [1]],
    ['harbor-citations', 'projects/harbor-notes/decisions/citations.md', pick('Keep the evidence', '保留证据'), 'decision', [3]],
    ['harbor-review', 'projects/harbor-notes/evolution.md', pick('Pilot review', '试用评审'), 'evolution', [2]],
  ];
  const docs = specs.map(([id, path, heading, type, indices], index) => {
    const claims = indices.map((n, i) => {
      const anchor = `a${index}${i}1`;
      return {anchor, kind:'paragraph', text:statements[n], raw_text:`${statements[n]} [cite: ${sourceId} ¶${n}] <!-- c:${anchor} -->`,
        citations:[{source_id:sourceId,from:n,to:n,snippet:statements[n],redaction_state:'included'}],flags:[]};
    });
    const related = index === 0 ? `\n\n## ${pick('Related pages','相关页面')}\n\n- [${specs[1][2]}](features/import.md)\n- [${specs[2][2]}](decisions/citations.md)\n- [${specs[3][2]}](evolution.md)` : '';
    const body = `# ${heading}\n\n${claims.map(c=>c.raw_text).join('\n\n')}${related}`;
    return {document_id:id,path,title:heading,frontmatter:{type,slug:id,title:heading},body,claims,archived:false};
  });
  const profile = {user_id:TENANT,display_name:pick('Demo library','演示知识库'),avatar:{initial:pick('D','演'),color:'slate'},gender:null,birth_year:null,
    locale:{city:null,country:null,timezone:'UTC',language:locale},industry:'other',industry_other:null,role:'other',role_other:null,level:'individual',level_style:'',
    occupation:pick('Synthetic documentation example','合成文档示例'),bio:pick('All names, sources and conversation below are invented.','所有名称、原始材料和对话均为虚构。'),interests:[],
    workspace:{operating_mode:null,primary_stack:null,automation_level:null,active_since:null},preferences:{response_language:locale,units:null,privacy_level:null},joined_at:null,source:'mock'};
  const dataset = {workspace:{schema_version:2,workspace_id:TENANT,export_policy:'full',domains:[{domain_id:'projects',skill_version:1,ontology:['project','feature','decision','evolution']}]},
    documents:{schema_version:2,documents:docs},graph:{schema_version:2,nodes:docs.map(d=>({id:d.document_id,path:d.path,title:d.title,type:d.frontmatter.type})),edges:docs.slice(1).map(d=>({source:docs[0].document_id,target:d.document_id,type:'link'}))},
    timeline:{schema_version:2,snapshots:[],jobs:[],patches:[],bundle_versions:[]},journal:[],claim_labels:[]};
  const detail = {source_id:sourceId,kind:'meeting',origin:'mock',source_class:'workstream',title:pick('Harbor Notes · pilot planning (synthetic)','港湾笔记 · 试用计划（合成示例）'),mime:'text/plain',checksum:'synthetic-docs-only',created_at:'2026-09-20T09:00:00Z',
    occurred_on:'2026-09-20',block_count:4,digested_at:'2026-09-20T09:05:00Z',archived_at:null,intake_plan:{canonical_treatment:'full',semantic_indexing:'full',rationale:'Synthetic demo',user_confirmed:true},
    meta:{occurred_on:'2026-09-20',timezone:'UTC',participants:[{display_name:pick('Demo author','示例作者')}]},blocks:statements.map((text,index)=>({index,text,section_path:[],images:[]})),structure:{sections:[]}};
  dataset.graph.nodes.push({id:`src:${sourceId}`,type:'source',path:detail.title,title:detail.title});
  const patch = {patch_id:'demo0002',job_id:'demo-job-2',ts:'2026-09-20T09:05:00Z',base_commit:'demo0001',changed_paths:[docs[0].path,docs[3].path],
    documents:[docs[0],docs[3]].map(d=>({document_id:d.document_id,path:d.path,change_type:'modified'})),sources_consumed:[sourceId],skill_version:1,effort:'compile',
    brief:pick('Record the pilot scope and next review; keep public release as an open decision.','记录试用范围和下次评审；公开发布仍保持未决。'),
    claims:[{type:'claim_added',path:docs[0].path,anchor:{document_id:docs[0].document_id,anchor:'a011'},after:docs[0].claims[1].raw_text,flags:[]},
      {type:'claim_added',path:docs[3].path,anchor:{document_id:docs[3].document_id,anchor:'a301'},after:docs[3].claims[0].raw_text,flags:[]}],escalations:[],merges:[],flag_counts:{},lineage:{driver:'synthetic-fixture'}};
  const earlier = {...patch,patch_id:'demo0001',job_id:'demo-job-1',base_commit:null,ts:'2026-09-18T10:00:00Z',brief:pick('Create the project page and record its evidence policy.','建立项目页面，记录证据保留原则。'),changed_paths:[docs[0].path,docs[2].path],claims:[{type:'claim_added',path:docs[2].path,anchor:{document_id:docs[2].document_id,anchor:'a201'},after:docs[2].claims[0].raw_text,flags:[]}]};
  const status = {configured:true,backend:'codex',label:'Codex',protocol:'app-server',spec:'agent:codex',live:true,exited:false,exit_code:null,agent_session_id:'demo-session',project_dir:'/demo/harbor-notes'};
  const reply = pick('I checked the planning source. The pilot covers **local document import** and **answers linked to their sources**.\n\nThe next review is **September 28**. Public release is still an open decision; the source does not say it has been approved.\n\nThis is a synthetic documentation conversation.', '我核对了计划材料。本轮试用包括 **本地文档导入** 和 **带原始出处的问答**。\n\n下一次评审是 **9 月 28 日**。公开发布仍是未决事项，材料没有说已经批准。\n\n这是一段合成的文档演示对话。');
  return {docs,dataset,profile,detail,patch,status,question:pick('What is in the pilot, and what is still undecided?','本轮试用包括什么？哪些事情还没决定？'),reply,
    history:{items:[patch,earlier].map(p=>({kind:'patch',ref:p.patch_id,ts:p.ts,payload:p})),page:{limit:25,total:2,next_cursor:null},counts:{patches:2,jobs:0,snapshots:0,total:2}}};
}
