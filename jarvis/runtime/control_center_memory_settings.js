/* Réglages mémoire du Control Center (jarvis-memory-intelligence-knowledge, Slice 10b : accroche, Slice 11 : écran).

   Servi et inséré dans la page ; volontairement quasi vide. La Slice 11 le remplit. Il ne rendra que la section
   `memory` de `GET /api/settings` (`schema`, `values`, `effective`, `downgraded`, `status`) : aucune borne, aucune
   liste d'options, aucun secret côté navigateur. Point de montage : `#memorySettingsMount`. */
(function(root){
  'use strict';
  const MOUNT_ID='memorySettingsMount';
  root.JarvisMemorySettings=Object.freeze({mountId:MOUNT_ID,mount:()=>root.document?root.document.getElementById(MOUNT_ID):null});
})(typeof window!=='undefined'?window:globalThis);
