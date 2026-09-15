import { getRawDb } from '@/db';
import { instagramAccount, isInstagramAgent } from '@/app/instagram-manual';

export const dynamic='force-dynamic';
export async function GET(request:Request) {
  if (!request.headers.get('oai-authenticated-user-id') && !(await isInstagramAgent(request))) return Response.json({error:'Accedi a Orbit'},{status:401});
  try {
    const row=await getRawDb().prepare('SELECT * FROM instagram_collection WHERE account_username=?').bind(instagramAccount).first();
    return Response.json(row ?? {requested_at:0,completed_request_at:0,last_seen:0,error:''},{headers:{'cache-control':'no-store'}});
  } catch { return Response.json({error:'Stato aggiornamento non disponibile'},{status:503}); }
}
export async function POST(request:Request) {
  if (!request.headers.get('oai-authenticated-user-id')) return Response.json({error:'Accedi a Orbit'},{status:401});
  if (request.headers.get('origin')!==new URL(request.url).origin || request.headers.get('x-orbit-manual')!=='1') return Response.json({error:'Richiesta non valida'},{status:403});
  try {
    const row=await getRawDb().prepare(`INSERT INTO instagram_collection (account_username,requested_at) VALUES (?,?)
      ON CONFLICT(account_username) DO UPDATE SET requested_at=excluded.requested_at, error=''
      RETURNING requested_at`).bind(instagramAccount,Date.now()).first();
    return Response.json(row,{status:202,headers:{'cache-control':'no-store'}});
  } catch { return Response.json({error:'Aggiornamento non richiesto: riprova'},{status:503}); }
}
