/* Memory Center du Control Center (jarvis-memory-intelligence-knowledge, Slice 10b : accroche, Slice 12 : vue).

   Servi et inséré dans la page ; volontairement quasi vide. La Slice 12 le remplit (vue « Sessions & Boards » étendue).
   Il ne lira que `/api/memory/*` (relais de `/v1/memory/*`, lecture seule). Point de montage : `#memoryCenterMount`. */
(function(root){
  'use strict';
  const MOUNT_ID='memoryCenterMount';
  root.JarvisMemoryCenter=Object.freeze({mountId:MOUNT_ID,mount:()=>root.document?root.document.getElementById(MOUNT_ID):null});
})(typeof window!=='undefined'?window:globalThis);
