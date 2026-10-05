"use strict";
async function refreshUsage(){
  try{
    const response=await fetch('/api/subscription');if(!response.ok)return;
    const data=await response.json();const label=document.querySelector('#quota-label');
    if(label&&data.unlimited){label.textContent='??? ? ????';return;}
    if(label)label.textContent=({free:'免费版',pro:'Pro',teacher:'教师版'}[data.plan]||data.plan)+' · 可用 '+data.remaining_quota+' 次'+(data.available_credits?'（含购买 '+data.available_credits+' 次）':'')+((data.reserved_quota+(data.reserved_credits||0))?' · '+(data.reserved_quota+(data.reserved_credits||0))+' 次处理中':'');
  }catch{}
}
document.addEventListener('pointerdown',()=>{fetch('/api/activity/active',{method:'POST'}).catch(()=>{});},{once:true});
document.addEventListener('keydown',()=>{fetch('/api/activity/active',{method:'POST'}).catch(()=>{});},{once:true});
refreshUsage();
