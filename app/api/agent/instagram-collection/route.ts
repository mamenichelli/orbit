import { getRawDb } from '@/db';
import { instagramAccount,isInstagramAgent } from '@/app/instagram-manual';

export const dynamic='force-dynamic';
export async function POST(request:Request) {
  if (!(await isInstagramAgent(request)))return Response.json({error:'Non autorizzato'},{status:401});
  let body:{action?:string;accountUsername?:string;version?:number};
  try {const raw=await request.text();if(raw.length>1000)throw Error();body=JSON.parse(raw);}catch{return Response.json({error:'Richiesta non valida'},{status:400});}
  if(!body || body.accountUsername!==instagramAccount || !['poll','started','finished','failed'].includes(body.action??''))return Response.json({error:'Account o azione non validi'},{status:400});
  if(['finished','failed'].includes(body.action??'') && (!Number.isSafeInteger(body.version)||Number(body.version)<0))return Response.json({error:'Versione non valida'},{status:400});
  const db=getRawDb(),now=Date.now();
  try {
    await db.prepare('INSERT INTO instagram_collection (account_username,last_seen) VALUES (?,?) ON CONFLICT(account_username) DO UPDATE SET last_seen=excluded.last_seen').bind(instagramAccount,now).run();
    if(body.action==='started') await db.prepare("UPDATE instagram_collection SET started_request_at=requested_at,started_at=?,error='' WHERE account_username=?").bind(now,instagramAccount).run();
    if(body.action==='finished')await db.prepare("UPDATE instagram_collection SET completed_request_at=MAX(completed_request_at,?),completed_at=?,error='' WHERE account_username=? AND started_request_at=?").bind(body.version,now,instagramAccount,body.version).run();
    if(body.action==='failed')await db.prepare("UPDATE instagram_collection SET error='Instagram non ha completato la raccolta: aggiornamento da riprovare' WHERE account_username=? AND started_request_at=?").bind(instagramAccount,body.version).run();
    const row=await db.prepare('SELECT * FROM instagram_collection WHERE account_username=?').bind(instagramAccount).first();
    return Response.json(row,{headers:{'cache-control':'no-store'}});
  }catch{return Response.json({error:'Coordinamento raccolta non disponibile'},{status:503});}
}
