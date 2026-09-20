// Included in the private page at build time. All offsets are raw whitespace-token
// indices, end-exclusive; no DOM text offsets or model drafts are saved as labels.
let spanAnswers = {};
const transcriptCache = {}, transcriptLoads = {}, spanSelections = {}, spanFull = {}, spanSample = {};
const spanUndo = {}, spanSaves = {}, spanErrors = {}, spanPending = {};
const spanEditing = {};
const SPAN_NAMES = {subject:"Subject", other:"Someone else", unclear:"Unclear"};

function transcriptFor(recording){
 if(transcriptCache[recording.key]) return Promise.resolve(transcriptCache[recording.key]);
 return transcriptLoads[recording.key] ||= (async()=>{
  const res=await fetch("api/transcript?key="+encodeURIComponent(recording.key));
  if(!res.ok) throw new Error("Could not load the transcript. Reload this page after the local server is updated.");
  const data=await res.json(), expected=D.transcript_index[recording.key];
  if(data.text_sha256!==expected.text_sha256 || data.token_count!==expected.token_count)
   throw new Error("The transcript changed. Reload the page before labeling it.");
  return transcriptCache[recording.key]=data;
 })().catch(error=>{delete transcriptLoads[recording.key];throw error;});
}
function spanWindow(recording,index){
 const data=transcriptCache[recording.key];
 if(spanFull[recording.key+":"+index]) return [0,data.tokens.length];
 const passage=index<0 ? recording.excerpts[spanSample[recording.key]||0] : recording.quotes[index];
 return [passage?.start||0,Math.min(passage?.end||130,data.tokens.length)];
}
function humanRanges(recording){
 if(spanAnswers[recording.key])return spanAnswers[recording.key].ranges;
 // Preserve earlier whole-quote human answers; "both" supplies no boundary.
 let ranges=[];
 for(const quote of recording.quotes){const answer=attrib[quote.qid]?.answer;
  if(["subject","other","unclear"].includes(answer)&&Number.isInteger(quote.quote_start))
   ranges=paintRanges(ranges,quote.quote_start,quote.quote_end,answer);}
 return ranges;
}
function draftLabels(data){
 if(data.draftLabels)return data.draftLabels;
 const values=Array.from({length:data.tokens.length},()=>new Set());
 for(const suggestion of data.suggestions) for(let i=suggestion.start;i<suggestion.end;i++) values[i].add(suggestion.speaker);
 return data.draftLabels=values.map(v=>v.size>1?"conflict":([...v][0]||"unknown"));
}
function statesFor(recording){
 const data=transcriptCache[recording.key], states=draftLabels(data).map(speaker=>({speaker,draft:true}));
 for(const range of humanRanges(recording)) for(let i=range.start;i<range.end;i++) states[i]={speaker:range.speaker,draft:false};
 return states;
}
function paintRanges(ranges,start,end,speaker,origin="human"){
 const kept=[];
 for(const range of ranges){
  if(range.end<=start||range.start>=end){kept.push({...range});continue;}
  if(range.start<start)kept.push({...range,end:start});
  if(range.end>end)kept.push({...range,start:end});
 }
 if(speaker)kept.push({start,end,speaker,origin});
 kept.sort((a,b)=>a.start-b.start);
 const merged=[];
 for(const range of kept){const last=merged.at(-1);
  if(last&&last.end===range.start&&last.speaker===range.speaker&&last.origin===range.origin)last.end=range.end;
  else merged.push(range);}
 return merged;
}
function rememberRanges(recording){(spanUndo[recording.key] ||= []).push(structuredClone(humanRanges(recording)));}
function saveRanges(recording,ranges){
 const data=transcriptCache[recording.key];
 const prior=spanAnswers[recording.key];
 if(prior&&(prior.text_sha256!==data.text_sha256||prior.token_count!==data.token_count)){
  spanErrors[recording.key]="Existing annotations refer to a different transcript; they were kept unchanged.";
  updateSpanStatus(recording);return;
 }
 const value={schema_version:1,key:recording.key,text_sha256:data.text_sha256,token_count:data.token_count,
  ranges,checked_by:"operator",updated_at:new Date().toISOString(),assisted:true,
  suggestions_sha256:data.suggestions_sha256};
 spanAnswers[recording.key]=value;spanErrors[recording.key]="";
 spanPending[recording.key]=(spanPending[recording.key]||0)+1;
 spanSaves[recording.key]=(spanSaves[recording.key]||Promise.resolve()).then(()=>saver.put("spans",recording.key,value)).then(result=>{
  if(result?.attribution) Object.assign(attrib,result.attribution);
  spanErrors[recording.key]="";
 }).catch(error=>{spanErrors[recording.key]=error.message||String(error);}).finally(()=>{
  spanPending[recording.key]--;updateSpanStatus(recording);renderList();
  if(cur===recording.key) el("status").textContent=complete(recording)?"All answered":`${outstanding(recording)} answers left on this recording`;
 });
 for(const quote of recording.quotes) attrib[quote.qid]={...(attrib[quote.qid]||{}),answer:null,review_status:"saving"};
 renderList();drawAllSpans(recording);
}
function updateSpanStatus(recording){
 if(cur!==recording.key)return;
 document.querySelectorAll(".span-status").forEach(node=>{
  node.classList.toggle("err",!!spanErrors[recording.key]);
  node.textContent=spanErrors[recording.key]?"Not saved: "+spanErrors[recording.key]:spanPending[recording.key]?"Saving markings…":
   spanAnswers[recording.key]?"Markings saved on this machine":"Suggestions are drafts until you confirm them";
 });
 document.querySelectorAll("[data-retry]").forEach(button=>button.hidden=!spanErrors[recording.key]);
}
function markSelection(recording,index,speaker){
 if(!writable)return;
 const selection=spanSelections[recording.key+":"+index];if(!selection)return;
 rememberRanges(recording);
 let ranges=humanRanges(recording);const id=recording.key+":"+index,prior=spanEditing[id];
 if(prior)ranges=paintRanges(ranges,prior[0],prior[1],null);
 delete spanEditing[id];
 saveRanges(recording,paintRanges(ranges,selection[0],selection[1],speaker));
}
function confirmDrafts(recording,index){
 if(!writable)return;
 const [start,end]=spanWindow(recording,index), states=statesFor(recording);let ranges=humanRanges(recording);
 rememberRanges(recording);
 for(let i=start;i<end;){const label=states[i];let j=i+1;
  while(j<end&&states[j].speaker===label.speaker&&states[j].draft===label.draft)j++;
  if(label.draft&&["subject","other"].includes(label.speaker))ranges=paintRanges(ranges,i,j,label.speaker,"model_confirmed");
  i=j;
 }
 saveRanges(recording,ranges);
}
function speechIndices(data,start,end){
 const indices=[];for(let i=start;i<end;i++) if(data.token_kinds[i]==="speech")indices.push(i);return indices;
}
function speechText(data,start,end){return speechIndices(data,start,end).map(i=>data.tokens[i]).join(" ");}
function quoteReview(recording,index){
 const quote=recording.quotes[index],data=transcriptCache[recording.key],ranges=humanRanges(recording);
 const words=speechIndices(data,quote.quote_start,quote.quote_end),speakers=new Set(),missing=[];let unsure=0;
 for(const i of words){const range=ranges.find(r=>r.start<=i&&i<r.end);
  if(!range)missing.push(i);else{speakers.add(range.speaker);if(range.speaker==="unclear")unsure++;}}
 const answer=missing.length||!words.length?null:unsure?"unclear":speakers.size>1?"both":[...speakers][0];
 return {answer,missing,unsure,total:words.length,reviewed:words.length-missing.length};
}
function reviewSummary(recording,index){
 const state=quoteReview(recording,index);
 let title,detail;
 if(state.missing.length){title=`${state.missing.length} quote words still need review`;
  detail=`${state.reviewed} of ${state.total} quote words reviewed. Label the remaining underlined words. Surrounding speech does not change this result.`;}
 else if(!state.total){title="No readable quote words";detail="This quote contains only caption markers; it remains unfinished.";}
 else {title=state.answer==="subject"?`Quote spoken by ${recording.person}`:state.answer==="other"?"Quote spoken by someone else":state.answer==="both"?"Quote includes both speakers":"Quote reviewed — speaker uncertain";
  detail=state.unsure?`You marked ${state.unsure} quote words as unsure. This is saved as an uncertain review.`:"Calculated from your reviewed quote words and saved automatically. No second answer is needed.";}
 return `<div class="quote-summary ${state.answer?"complete":"pending"}" role="status"><strong>${esc(title)}</strong><p>${esc(detail)}</p>${state.missing.length?'<button type="button" class="opt" data-next-unreviewed>Review remaining quote words</button>':""}</div>`;
}
function spanToolbar(recording,index){
 const node=document.querySelector(`[data-span-editor="${index}"]`);if(!node)return;
 const id=recording.key+":"+index,selection=spanSelections[id],data=transcriptCache[recording.key];
 const text=selection ? speechText(data,...selection) : "Drag across words below, then choose who said them.";
 node.querySelector(".span-selection").textContent=selection?`Selected ${speechIndices(data,...selection).length} words: ${text}`:text;
 node.querySelectorAll("[data-paint]").forEach(b=>b.disabled=!selection||!speechIndices(data,...selection).length||!writable);
 node.querySelectorAll("[data-w]").forEach(word=>word.classList.toggle("selected-word",!!selection&&+word.dataset.w>=selection[0]&&+word.dataset.w<selection[1]));
 const sliders=node.querySelector(".span-boundaries");sliders.hidden=!selection;
 if(selection){
  const [windowLo,windowHi]=spanWindow(recording,index), speech=speechIndices(data,windowLo,windowHi);
  const lo=speech[0]??windowLo,hi=(speech.at(-1)??(windowHi-1))+1;
  for(const [field,value,min,max] of [["start",selection[0],lo,selection[1]-1],["end",selection[1],selection[0]+1,hi]]){
   const input=sliders.querySelector(`[data-edge="${field}"]`);input.min=min;input.max=max;input.value=value;
   input.setAttribute("aria-valuetext",data.tokens[field==="start"?value:value-1]);
  }
 }
}
function drawAllSpans(recording){
 if(cur!==recording.key)return;
 document.querySelectorAll("[data-span-editor]").forEach(node=>drawSpanEditor(recording,+node.dataset.spanEditor));
}
function drawSpanEditor(recording,index){
 const root=document.querySelector(`[data-span-editor="${index}"]`);if(!root||cur!==recording.key)return;
 const scrollTop=root.querySelector(".span-transcript")?.scrollTop||0;
 const data=transcriptCache[recording.key];if(!data)return;
 const saved=spanAnswers[recording.key];
 if(saved&&(saved.text_sha256!==data.text_sha256||saved.token_count!==data.token_count)){
  root.textContent="Saved markings refer to a different transcript. They have been preserved; resolve the changed transcript before editing.";return;
 }
 const id=recording.key+":"+index,[lo,hi]=spanWindow(recording,index),states=statesFor(recording);
 const quote=index>=0?recording.quotes[index]:null;
 const spoken=speechIndices(data,lo,hi);
 const markable=spoken.some(i=>states[i].draft&&["subject","other"].includes(states[i].speaker));
 const known=spoken.filter(i=>draftLabels(data)[i]!=="unknown").length;
 const timestamps=new Map(data.times);
 let words="";
 for(let i=lo;i<hi;i++){
  const state=states[i],token=data.tokens[i],isQuote=quote&&i>=quote.quote_start&&i<quote.quote_end;
  const tip=state.speaker==="unknown"?"Unknown — no attribution":state.speaker==="conflict"?"Models disagree — review this text":
   `${state.draft?"Model suggestion (unconfirmed)":"Human reviewed"}: ${state.speaker==="subject"?recording.person:SPAN_NAMES[state.speaker]}`;
  const kind=data.token_kinds[i];
  if(kind==="timestamp"){
   if(spanFull[id]) words+=`<span class="caption-time" contenteditable="false"><a href="https://www.youtube.com/watch?v=${encodeURIComponent(recording.video_id)}&t=${timestamps.get(i)}s" target="_blank" rel="noopener">▶ ${fmtT(timestamps.get(i))}</a></span>`;
  }else if(kind==="turn") words+='<span class="caption-turn" contenteditable="false" aria-label="Caption speaker break"> / </span>';
  else if(kind!=="speech"){
   if(kind==="gap"&&(i===lo||data.token_kinds[i-1]!=="gap")) words+='<span class="caption-gap" contenteditable="false" title="Words missing or obscured in the captions; not part of speaker labeling">caption gap</span> ';
  }else words+=`<span data-w="${i}" class="word ${state.speaker} ${state.draft?"draft":"reviewed"} ${isQuote?"evidence":""}" title="${esc(tip)}">${esc(token)} </span>`;

 }
 const marked=humanRanges(recording).filter(range=>range.start<hi&&range.end>lo&&speechIndices(data,Math.max(lo,range.start),Math.min(hi,range.end)).length);
 root.innerHTML=`<div class="span-top"><b>Mark who is speaking</b><button type="button" class="opt" data-expand>${spanFull[id]?"Back to passage":"Expand to full transcript"}</button></div>
  <p class="span-instructions">Select words, then choose who said them. Repeat for separate passages. Caption gaps and playback times are skipped automatically.</p>
  <div class="span-legend"><span class="subject reviewed">Subject · reviewed</span><span class="other reviewed">Other · reviewed</span><span class="subject draft">Dashed · model draft</span><span>Plain · not reviewed</span>${quote?'<span class="evidence">Underline · quote being checked</span>':""}</div>
  <p class="span-model">${known?"Model estimates cover "+known+" of these "+spoken.length+" words. Confirm or correct the dashed suggestions.":"No model suggestions for this passage. Label the words you can identify; use “Unsure” when you cannot identify the speaker."} ${states.slice(lo,hi).some(s=>s.speaker==="conflict")?"Models disagree on the dotted words; review those yourself.":""}</p>
  ${index<0&&!spanFull[id]?`<label class="span-samples">Passage <select data-sample>${(recording.excerpts||[]).map((e,i)=>`<option value="${i}" ${i===(spanSample[recording.key]||0)?"selected":""}>${Math.round(e.at*100)}% into recording</option>`).join("")}</select></label>`:""}
  <div class="span-actions"><div class="span-selection" aria-live="polite"></div><div class="opts">
   <button class="opt y" type="button" data-paint="subject">Mark as ${esc(recording.person)}</button>
   <button class="opt n" type="button" data-paint="other">Someone else</button><button class="opt" type="button" data-paint="unclear">Unsure</button>
   <button class="opt" type="button" data-paint="">Clear human marks</button></div>
   <div class="span-boundaries" hidden><label>Selection start <input type="range" data-edge="start" aria-label="Selection start word"></label><label>Selection end <input type="range" data-edge="end" aria-label="Selection end word"></label></div>
  </div>
  <div class="span-transcript" tabindex="0" role="region" aria-label="Transcript passage for speaker annotation">${words}</div>
  <div class="opts"><button type="button" class="opt" data-confirm ${!writable||!markable?"disabled":""}>Confirm suggested spans in ${spanFull[id]?"full transcript":"this passage"}</button>
   <button type="button" class="opt" data-undo ${!writable||!spanUndo[recording.key]?.length?"disabled":""}>Undo marking</button>
   <button type="button" class="opt" data-retry ${!spanErrors[recording.key]?"hidden":""}>Retry save</button></div>
  <div class="span-status status" role="status"></div>
  <details class="span-ranges"><summary>${marked.length} reviewed span${marked.length===1?"":"s"} in view</summary>
   ${marked.map(range=>`<div class="span-range"><b>${range.speaker==="subject"?esc(recording.person):SPAN_NAMES[range.speaker]}</b> <span>${esc(speechText(data,range.start,Math.min(range.end,range.start+12)))}${range.end-range.start>12?"…":""}</span><button type="button" class="opt" data-select-span="${range.start},${range.end}">Select / adjust</button><button type="button" class="opt" data-remove-span="${range.start},${range.end}" ${writable?"":"disabled"}>Remove</button></div>`).join("")}
  </details>
  ${quote?reviewSummary(recording,index):""}`;

 root.querySelector("[data-expand]").onclick=()=>{spanFull[id]=!spanFull[id];delete spanSelections[id];delete spanEditing[id];drawSpanEditor(recording,index);};
 const sample=root.querySelector("[data-sample]");if(sample)sample.onchange=()=>{spanSample[recording.key]=+sample.value;delete spanSelections[id];drawSpanEditor(recording,index);};
 const area=root.querySelector(".span-transcript");
 area.scrollTop=scrollTop;
 const capture=()=>{
  const selection=window.getSelection();if(!selection||selection.isCollapsed||!selection.rangeCount)return;
  const range=selection.getRangeAt(0);
  if(!area.contains(range.startContainer)||!area.contains(range.endContainer))return;
  const selected=[...area.querySelectorAll("[data-w]")].filter(word=>range.intersectsNode(word));
  if(selected.length){delete spanEditing[id];spanSelections[id]=[+selected[0].dataset.w,+selected.at(-1).dataset.w+1];spanToolbar(recording,index);}
 };
 area.onmouseup=capture;area.onkeyup=capture;
 root.querySelectorAll("[data-paint]").forEach(button=>button.onclick=()=>markSelection(recording,index,button.dataset.paint||null));
 root.querySelectorAll("[data-edge]").forEach(input=>input.oninput=()=>{
  const selection=spanSelections[id];let edge=+input.value;
  if(input.dataset.edge==="start"){while(edge<selection[1]-1&&data.token_kinds[edge]!=="speech")edge++;selection[0]=edge;}
  else{while(edge>selection[0]+1&&data.token_kinds[edge-1]!=="speech")edge--;selection[1]=edge;}
  spanToolbar(recording,index);
 });
 root.querySelector("[data-confirm]").onclick=()=>confirmDrafts(recording,index);
 root.querySelector("[data-undo]").onclick=()=>{const ranges=spanUndo[recording.key]?.pop();if(ranges)saveRanges(recording,ranges);};
 root.querySelector("[data-retry]").onclick=()=>saveRanges(recording,humanRanges(recording));
 root.querySelectorAll("[data-select-span]").forEach(button=>button.onclick=()=>{
  const range=button.dataset.selectSpan.split(",").map(Number);spanEditing[id]=[...range];
  if(range[0]<lo||range[1]>hi){spanFull[id]=true;spanSelections[id]=range;drawSpanEditor(recording,index);}
  else{spanSelections[id]=range;spanToolbar(recording,index);}
 });
 root.querySelectorAll("[data-remove-span]").forEach(button=>button.onclick=()=>{
  const [a,b]=button.dataset.removeSpan.split(",").map(Number);rememberRanges(recording);saveRanges(recording,paintRanges(humanRanges(recording),a,b,null));
 });
 const remaining=root.querySelector("[data-next-unreviewed]");if(remaining)remaining.onclick=()=>{
  const missing=quoteReview(recording,index).missing;if(!missing.length)return;
  const start=missing[0];let end=start+1;
  while(end<quote.quote_end&&(data.token_kinds[end]!=="speech"||missing.includes(end)))end++;
  spanSelections[id]=[start,end];delete spanEditing[id];spanToolbar(recording,index);
  root.querySelector(`[data-w="${start}"]`)?.scrollIntoView({block:"center",behavior:"smooth"});
 };
 spanToolbar(recording,index);updateSpanStatus(recording);
}
function mountSpanEditors(recording){
 if(!D.transcript_index?.[recording.key])return;
 transcriptFor(recording).then(()=>drawAllSpans(recording)).catch(error=>{
  if(cur===recording.key)document.querySelectorAll("[data-span-editor]").forEach(node=>node.textContent=error.message);
 });
}
window.addEventListener("beforeunload",event=>{
 if(Object.values(spanPending).some(Boolean)||Object.values(spanErrors).some(Boolean)){
  event.preventDefault();event.returnValue="";
 }
});
