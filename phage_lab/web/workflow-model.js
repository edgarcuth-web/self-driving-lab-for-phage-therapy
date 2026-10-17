/* Browser-only synthetic scenario model. No scientific or physical execution. */
(function (root) {
  "use strict";
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const CASES = {
    mixed: { title: "混合菌样本", sample_id: "DEMO-2026-001", sample_type: "模拟呼吸道样本", collected_at: "2026-10-17T09:00",
      isolates: [
        { id: "ISO-001", name: "肺炎克雷伯菌", species: "Klebsiella pneumoniae", library_key: "kp" },
        { id: "ISO-002", name: "铜绿假单胞菌", species: "Pseudomonas aeruginosa", library_key: "pa" },
        { id: "ISO-003", name: "金黄色葡萄球菌", species: "Staphylococcus aureus", library_key: "sa" },
      ] },
    single: { title: "单菌样本", sample_id: "DEMO-2026-002", sample_type: "模拟尿液样本", collected_at: "2026-10-17T10:30",
      isolates: [{ id: "ISO-004", name: "大肠埃希菌", species: "Escherichia coli", library_key: "ec" }] },
    unmatched: { title: "库内未匹配", sample_id: "DEMO-2026-003", sample_type: "模拟环境样本", collected_at: "2026-10-17T11:00",
      isolates: [{ id: "ISO-005", name: "未收录菌株", species: "Uncatalogued demo isolate", library_key: "unknown" }] },
  };
  // Opaque fixture IDs are not real accessions or drug recommendations.
  const CATALOG = {
    kp: { phage: ["PHG-DEMO-K01", "PHG-DEMO-K02"], antibiotic: ["ABX-DEMO-01", "ABX-DEMO-02"] },
    pa: { phage: ["PHG-DEMO-P01"], antibiotic: ["ABX-DEMO-03"] },
    sa: { phage: ["PHG-DEMO-S01"], antibiotic: ["ABX-DEMO-04"] },
    ec: { phage: ["PHG-DEMO-E01", "PHG-DEMO-E02"], antibiotic: ["ABX-DEMO-05"] },
  };
  const NODES = [
    { id: "sample", number: "01", title: "病人取样", en: "PATIENT SAMPLE", icon: "◎", start: 0, end: 1, deps: [], phase: "clinical",
      description: "登记模拟样本，建立样本身份与采集记录。" },
    { id: "isolate", number: "02A", title: "细菌基因检测", en: "FRAGMENT DETECTION", icon: "⠿", start: 1, end: 2, deps: ["sample"], phase: "clinical",
      description: "模拟短读段与人工参考窗比对，结合读段、覆盖率、一致性及阴性对照生成未校准的支持评分。" },
    { id: "phage", number: "03A", title: "噬菌体匹配", en: "PHAGE MATCHING", icon: "✳", start: 2, end: 3, deps: ["isolate"], phase: "phage",
      description: "为每株细菌查找模拟候选；保留未匹配项。" },
    { id: "antibiotic", number: "03B", title: "抗生素匹配", en: "ANTIBIOTIC MATCHING", icon: "⊕", start: 2, end: 3, deps: ["isolate"], phase: "antibiotic",
      description: "与噬菌体匹配同时开始，独立输出待验证的模拟候选。" },
    { id: "prepare", number: "04", title: "噬菌体制备", en: "PHAGE PREPARATION", icon: "◴", start: 3, end: 10, deps: ["phage"], phase: "phage",
      description: "场景设定：匹配后制备约 7 天；不阻塞抗生素匹配。" },
    { id: "design", number: "05", title: "筛选与实验设计", en: "DESIGN", icon: "◇", start: 10, end: 11, deps: ["prepare"], phase: "lab",
      description: "展示 CandidateSet → 冻结 ExperimentSpec 的数据衔接。" },
    { id: "test", number: "06", title: "实验测试", en: "TEST", icon: "⌁", start: 11, end: 12, deps: ["design"], phase: "lab",
      description: "展示制备、转运、测试和读数的虚拟流程边界。" },
    { id: "learn", number: "07", title: "评估与反馈", en: "LEARN", icon: "↻", start: 12, end: 13, deps: ["test"], phase: "lab",
      description: "展示结果复核与下一轮筛选；无真实表型或自动训练。" },
  ];
  function artificialDna(seed) {
    let value = seed;
    return Array.from({length:60}, () => {
      value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
      return 'ACGT'[(value >>> 24) % 4];
    }).join('');
  }
  function detectionRecord(id, isolateId, seed, reads, controlReads, coveredBases, mismatches, unresolved = false) {
    const fragments = mismatches.map((count, index) => {
      const reference = artificialDna(seed + index * 97), query = [...reference];
      for (let i = 0; i < count; i++) {
        const position = (i * 7 + index * 3) % query.length;
        query[position] = 'ACGT'[('ACGT'.indexOf(query[position]) + 1) % 4];
      }
      return {id:`FRAG-DEMO-${id}-${index + 1}`, marker:`人工标记窗 ${index + 1}`, reference_id:`SYN-REF-${id}-${index + 1}`,
        sequence:query.join(''), reference_sequence:reference, length_bp:60, matched_bases:60-count,
        identity_percent:Math.round((60-count)/60*1000)/10, synthetic:true};
    });
    const identity = fragments.reduce((sum, f)=>sum+f.matched_bases, 0) / 120 * 100;
    const coverage = coveredBases / 300 * 100, ratio = reads / Math.max(controlReads, 1);
    const score = Math.round(1000 * (.35*Math.min(reads/500,1) + .3*coverage/100 +
      .25*Math.max(0,Math.min((identity-85)/15,1)) + .1*Math.min(ratio/20,1))) / 10;
    return {id, isolate_id:isolateId, classification:unresolved?'unclassified_bacterial_signal':'candidate_species',
      species_assignment:unresolved?null:CASES.mixed.isolates.concat(CASES.single.isolates).find(i=>i.id===isolateId)?.species,
      metrics:{unique_reads:reads, control_reads:controlReads, sample_control_ratio:Math.round(ratio*10)/10,
        covered_bases:coveredBases, reference_window_bp:300, coverage_percent:Math.round(coverage*10)/10, identity_percent:Math.round(identity*10)/10},
      confidence:{score, scale:'0–100', level:score>=85?'high':score>=60?'moderate':'low', method:'synthetic-support-v1', calibrated:false, clinical_probability:null},
      fragments, simulated:true, confirmed_new_species:false,
      interpretation:unresolved?'存在未分类细菌样片段；物种未确定，须排除参考库缺口、低特异比对和背景污染。':'仅为模拟候选物种；不代表真实鉴定、感染诊断或药敏结果。'};
  }
  function makeDetection(caseId) {
    const identified = caseId === 'mixed' ? [
      detectionRecord('DET-001','ISO-001',101,1840,5,281,[0,1]),
      detectionRecord('DET-002','ISO-002',202,530,8,225,[1,1]),
      detectionRecord('DET-003','ISO-003',303,220,12,200,[2,2]),
    ] : caseId === 'single' ? [detectionRecord('DET-004','ISO-004',404,3100,3,292,[0,0])] : [];
    const unclassified = caseId === 'single' ? [] : [caseId === 'mixed'
      ? detectionRecord('UNCL-001',null,505,420,20,218,[8,9],true)
      : detectionRecord('UNCL-002','ISO-005',606,18,9,54,[10,11],true)];
    return {method:'synthetic-mngs-v1', reference_database:'artificial-reference-windows-v1', simulated:true,
      score_definition:'35%读段支持 + 30%人工参考窗覆盖 + 25%一致性支持 + 10%样本/对照比；仅为演示权重，未校准。',
      sequence_notice:'全部60 nt片段与参考窗均为确定性人工序列；不对应真实菌株基因、PCR引物或可用的检测靶标。',
      identified, unclassified};
  }
  function createState(caseId, metadata = {}) {
    if (!Object.hasOwn(CASES, caseId)) throw new Error("未知模拟样本");
    const fixture = copy(CASES[caseId]);
    return { caseId, day: 0, sample: { sample_id: fixture.sample_id, sample_type: fixture.sample_type,
      collected_at: fixture.collected_at, ...metadata }, isolates: fixture.isolates, detection:makeDetection(caseId) };
  }
  function isolatesOf(state) { return copy(state.isolates); }
  function detectionOf(state) { return state.day >= 2 ? copy(state.detection) : null; }
  function matchesOf(state, kind) {
    return isolatesOf(state).map(isolate => ({ isolate_id: isolate.id, name: isolate.name,
      candidates: [...(CATALOG[isolate.library_key]?.[kind] || [])], status: CATALOG[isolate.library_key] ? "synthetic_candidates" : "unresolved",
      probability: "not_estimated", evidence_class: "none" }));
  }
  function statusOf(state, id) {
    const n = NODES.find(node => node.id === id);
    if (!n) throw new Error("未知节点");
    if (n.deps.some(dep => ["review", "blocked"].includes(statusOf(state, dep)))) return "blocked";
    if (state.day < n.start) return "waiting";
    if (state.day < n.end) return "running";
    if (["phage", "antibiotic"].includes(id) && matchesOf(state, id).some(item => !item.candidates.length)) return "review";
    return "succeeded";
  }
  function advance(state, days) {
    if (!Number.isFinite(days) || days < 0) throw new Error("场景时间必须为非负数");
    state.day = Math.min(13, Math.round((state.day + days) * 1e9) / 1e9);
    return state;
  }
  function outputOf(state, id) {
    if (!["succeeded", "review"].includes(statusOf(state, id))) return null;
    switch (id) {
      case "sample": return { metadata: copy(state.sample), simulated: true };
      case "isolate": return { library: "synthetic-isolation-v1", isolates: isolatesOf(state), detection:detectionOf(state), completeness: "all_fixture_isolates_only", simulated: true };
      case "phage": case "antibiotic": return { catalog: "synthetic-matching-v1", matches: matchesOf(state, id), evidence_class: "none" };
      case "prepare": return { preparation_days: 7, assumption: "user_scenario", physical_execution: false, status: "illustrated_only" };
      case "design": return { concepts: ["CandidateSet", "ExperimentSpec v2"], domain_artifacts_created: false, membership: "illustration_only" };
      case "test": return { physical_execution: false, device_commands_sent: 0, evidence_class: "none", measurements_created: 0 };
      case "learn": return { phenotype_created: false, model_updated: false, probabilities: "not_estimated", next_screening: "illustration_only" };
    }
  }
  function reportOf(state) {
    return { schema: "clinical-workflow-presentation-v1", simulated: true, execution_mode: "presentation_only", physical_execution: false,
      evidence_class: "none", probabilities: "not_estimated", scenario_day: state.day, case_id: state.caseId, sample: copy(state.sample),
      limitations: ["本地合成数据；未执行真实菌株识别或药敏分析。", "候选不代表临床建议、感染概率或疗效证据。", "制备约 7 天为场景设定；无真实设备调用或领域对象写入。"],
      nodes: NODES.map(n => ({ id: n.id, title: n.title, depends_on: n.deps, status: statusOf(state, n.id), output: outputOf(state, n.id) })) };
  }
  // Presentation pacing is deliberately separate from the scenario's biological clock.
  function tourFrame(seconds, caseId) {
    const steps = [
      ['intake',12,0,1,'sample','workflow-title','一份样本，开启两条路径','登记虚构样本身份与采集信息，建立后续检测、候选匹配与报告的追踪起点。'],
      ['detect',18,1,2,'isolate','workflow-title','从片段信号，到候选细菌','用人工片段演示比对、覆盖和对照判读。检测支持分随数据返回；它不是确诊概率。'],
      ['review',12,2,2,'isolate',caseId==='single'?'isolates-title':'unknown-detection','把不确定性留在流程里',caseId==='single'?'本例未保留未分类信号。候选物种仍需独立验证，模拟高分也不是临床结论。':'查看未分类细菌样信号及较低支持的候选。物种未确定的信号进入复核，不自动进入药物或噬菌体匹配。'],
      ['match',16,2,3,'phage','workflow-title','同一份清单，同时匹配两路候选','噬菌体与抗生素分支并行启动；候选编号来自虚构库，不表示药敏结果或治疗建议。'],
      ['prepare',28,3,10,'prepare','parallel-title','抗生素候选已返回，噬菌体继续制备','抗生素候选在 D+3 返回；噬菌体制备跨越 D+3 至 D+10。7天是场景设定，播放已压缩时间。'],
      ['design',12,10,11,'design','workflow-title','候选交接，形成实验设计','展示候选集到冻结实验意图的交接。这里只演示数据流，不创建真实实验或制备订单。'],
      ['test',10,11,12,'test','workflow-title','实验执行，留下可追踪记录','演示测试与读数的流程位置。未连接真实设备，也没有生成可用于判定疗效的物理证据。'],
      ['learn',12,12,13,'learn','workflow-title','复核结果，进入下一轮筛选','主流程完成后仍保留待复核信号。流程成功不会自动转化为生物学成功，也不会自动训练模型。'],
      ['report',12,13,13,'learn','clinical-report-title','将结构化结果交给报告','启用自动生成后，由 Kimi K3 整理结构化摘要。实际配置、生成进度和草稿结果显示在报告区；导览结束不代表报告已生成。'],
    ];
    if (caseId==='unmatched') {
      steps.splice(4,4);
      steps[4] = ['report',12,3,3,'phage','clinical-report-title','没有候选，也是一种明确结果','库内未匹配，后续制备与实验已阻断。保留未分类信号和待复核结论，报告依据实际停止状态整理。'];
    }
    const duration = steps.reduce((sum,item)=>sum+item[1],0);
    const elapsed = Math.max(0,Math.min(Number.isFinite(seconds)?seconds:0,duration));
    let start = 0, index = 0;
    for (;index<steps.length-1;index++) {if (elapsed<start+steps[index][1]) break; start+=steps[index][1];}
    const [key,length,from,to,node,target,title,body] = steps[index];
    return {key,index,total:steps.length,start,end:start+length,duration,elapsed,node,target,title,body,
      day:from+(to-from)*Math.min((elapsed-start)/length,1),finished:elapsed>=duration};
  }
  function timelineOf(state) {
    const status = statusOf(state,'prepare');
    return {antibiotic:{status:statusOf(state,'antibiotic'),readyDay:3},
      prepare:{status,duration:7,progress:status==='blocked'?0:Math.max(0,Math.min((state.day-3)/7,1))}};
  }
  function reviewOf(state) {
    const detection = detectionOf(state);
    if (!detection) return [];
    return [...detection.identified.filter(item=>item.confidence.score<85),...detection.unclassified]
      .map(item=>({id:item.id,reason:item.classification==='candidate_species'?'候选物种支持较弱':'未分类细菌样信号'}));
  }
  const api = { CASES, NODES, createState, advance, statusOf, isolatesOf, detectionOf, outputOf, reportOf, tourFrame, timelineOf, reviewOf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ClinicalWorkflow = api;
})(typeof window !== "undefined" ? window : this);
