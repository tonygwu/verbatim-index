// Corrections overlay raw-token anchors; they never renumber speaker ranges.
let correctionAnswers = {};
const correctionForms = {}, correctionPending = {}, correctionErrors = {};
function editsFor(recording){return correctionAnswers[recording.key]?.edits||[];}
function correctionBounds(recording,start,end){
 for(const edit of editsFor(recording)) if(edit.start<end&&edit.end>start){
  start=Math.min(start,edit.start);end=Math.max(end,edit.end);
 }
 return [start,end];
}
function readingText(recording,start,end){
 const data=transcriptCache[recording.key],edits=editsFor(recording),parts=[];
 for(let i=start;i<end;){const edit=edits.find(e=>e.start<=i&&i<e.end);
  if(edit){parts.push(edit.replacement);i=edit.end;}
  else{if(data.token_kinds[i]==="speech")parts.push(data.tokens[i]);i++;}
 }
 return parts.join(" ");
}
function correctionPanel(recording,index,lo,hi){
 const id=recording.key+":"+index,form=correctionForms[id];
 const edits=editsFor(recording).filter(e=>e.start<hi&&e.end>lo);
 const error=correctionErrors[recording.key],busy=correctionPending[recording.key];
 return `${form?`<div class="correction-form">
  <b>Correct the captions</b><p class="sub">Original: ${esc(form.original)}</p>
  <label>What was actually said?<textarea data-corrected-text rows="2" ${busy?"disabled":""}>${esc(form.text)}</textarea></label>
  <div class="opts"><button class="opt" type="button" data-save-correction ${busy?"disabled":""}>${busy?"Saving…":"Save correction"}</button><button class="opt" type="button" data-cancel-correction ${busy?"disabled":""}>Cancel</button></div>
  <p class="sub">Changes the displayed wording. Your speaker markings stay attached to the same passage.</p></div>`:""}
  ${error?`<p class="status err" role="alert">Correction not saved: ${esc(error)}</p>`:""}
  ${busy&&!form?'<p class="status">Saving correction…</p>':""}
  ${edits.length?`<details class="text-corrections"><summary>${edits.length} text correction${edits.length===1?"":"s"} in view · saved locally</summary>
   ${edits.map(e=>`<div class="text-correction"><div><del>${esc(e.original)}</del> → <strong>${esc(e.replacement)}</strong></div><div class="opts"><button class="opt" type="button" data-edit-correction="${e.start},${e.end}">Edit correction</button><button class="opt" type="button" data-restore-correction="${e.start},${e.end}" ${busy?"disabled":""}>Restore original</button></div></div>`).join("")}
   <p class="sub">Original captions and judge quotes are preserved. Existing scores have not been recalculated.</p></details>`:""}`;
}
function openCorrection(recording,index,bounds){
 if(!writable||correctionPending[recording.key])return;
 const data=transcriptCache[recording.key],id=recording.key+":"+index;
 const [start,end]=correctionBounds(recording,...bounds);
 if(data.token_kinds.slice(start,end).some(k=>k!=="speech")){
  correctionErrors[recording.key]="Select spoken words within one caption segment, without gaps or timestamps.";
  drawAllSpans(recording);return;
 }
 const original=data.tokens.slice(start,end).join(" "),text=readingText(recording,start,end);
 correctionForms[id]={start,end,original,text,initial:text};delete correctionErrors[recording.key];
 drawSpanEditor(recording,index);
 document.querySelector(`[data-span-editor="${index}"] [data-corrected-text]`)?.focus();
}
async function persistCorrections(recording,edits,index){
 if(correctionPending[recording.key])return;
 const data=transcriptCache[recording.key],prior=correctionAnswers[recording.key];
 const value={key:recording.key,text_sha256:data.text_sha256,token_count:data.token_count,
  edits,revision:prior?.revision||0,checked_by:"operator"};
 correctionPending[recording.key]=true;delete correctionErrors[recording.key];drawAllSpans(recording);
 try{
  const result=await saver.put("corrections",recording.key,value);
  correctionAnswers[recording.key]=result.correction;
  delete correctionForms[recording.key+":"+index];
 }catch(error){correctionErrors[recording.key]=error.message||String(error);}
 finally{correctionPending[recording.key]=false;drawAllSpans(recording);renderList();}
}
function bindCorrections(root,recording,index){
 const id=recording.key+":"+index,form=correctionForms[id];
 root.querySelector('[data-correct-text]').onclick=()=>{
  const selected=spanSelections[id];if(selected)openCorrection(recording,index,selected);
 };
 const input=root.querySelector('[data-corrected-text]');if(input)input.oninput=()=>{form.text=input.value;};
 const cancel=root.querySelector('[data-cancel-correction]');if(cancel)cancel.onclick=()=>{
  delete correctionForms[id];delete correctionErrors[recording.key];drawSpanEditor(recording,index);
 };
 const save=root.querySelector('[data-save-correction]');if(save)save.onclick=()=>{
  const replacement=form.text.trim().replace(/\s+/g," ");
  if(!replacement){correctionErrors[recording.key]="Enter the words you hear. To undo an edit, use Restore original.";drawSpanEditor(recording,index);return;}
  const edits=editsFor(recording).filter(e=>e.end<=form.start||e.start>=form.end);
  if(replacement!==form.original)edits.push({start:form.start,end:form.end,original:form.original,replacement});
  persistCorrections(recording,edits.sort((a,b)=>a.start-b.start),index);
 };
 root.querySelectorAll('[data-edit-correction]').forEach(b=>b.onclick=()=>openCorrection(recording,index,b.dataset.editCorrection.split(',').map(Number)));
 root.querySelectorAll('[data-restore-correction]').forEach(b=>b.onclick=()=>{
  const [a,z]=b.dataset.restoreCorrection.split(',').map(Number);
  persistCorrections(recording,editsFor(recording).filter(e=>e.start!==a||e.end!==z),index);
 });
}
window.addEventListener('beforeunload',event=>{
 if(Object.values(correctionPending).some(Boolean)||Object.values(correctionErrors).some(Boolean)||
    Object.values(correctionForms).some(f=>f.text!==f.initial)){
  event.preventDefault();event.returnValue="";
 }
});
