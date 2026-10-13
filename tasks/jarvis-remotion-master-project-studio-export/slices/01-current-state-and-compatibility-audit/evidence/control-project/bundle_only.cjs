const path=require('node:path');const [rt,work,out]=process.argv.slice(2);
const {bundle}=require(path.join(rt,'node_modules','@remotion','bundler'));
bundle({entryPoint:path.join(work,'studio-root.tsx'),outDir:out,rootDir:work,publicDir:path.join(work,'public'),enableCaching:false})
 .then(()=>console.log(JSON.stringify({bundled:true}))).catch(e=>{console.log(JSON.stringify({bundled:false,error:String(e.message).slice(0,300)}));process.exit(1)});
