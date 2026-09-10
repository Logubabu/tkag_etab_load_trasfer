import json,csv,os,traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from etabs_bridge import EtabsBridge
from e2k_reader import E2KReader
from ram_cpt import write_copy,inspect_template,resolve_mapping
BASE=Path(__file__).resolve().parent; CFG_PATH=BASE/'config.json'
class App(tk.Tk):
    def __init__(self):
        super().__init__();self.title('ETABS EDB/E2K → RAM Concept Load Transfer v2');self.geometry('1240x790')
        self.cfg=json.loads(CFG_PATH.read_text());self.bridge=EtabsBridge(self.cfg);self.e2k=None;self.records=[];self.source=tk.StringVar();self.mode=tk.StringVar(value='EDB');self._build()
    def _build(self):
        top=ttk.Frame(self,padding=10);top.pack(fill='x');ttk.Label(top,text='ETABS EDB / E2K → RAM Concept',font=('Segoe UI',16,'bold')).grid(row=0,column=0,columnspan=6,sticky='w')
        ttk.Label(top,text='Source:').grid(row=1,column=0);ttk.Combobox(top,textvariable=self.mode,values=['EDB','E2K'],width=8,state='readonly').grid(row=1,column=1);ttk.Entry(top,textvariable=self.source,width=80).grid(row=1,column=2,padx=4);ttk.Button(top,text='Browse',command=self.browse_source).grid(row=1,column=3);ttk.Button(top,text='1. Read Model',command=self.read_source).grid(row=1,column=4,padx=4);ttk.Button(top,text='Open Config',command=lambda:os.startfile(CFG_PATH)).grid(row=1,column=5)
        ttk.Label(top,text='Story:').grid(row=2,column=0,pady=7);self.story=ttk.Combobox(top,width=32,state='readonly');self.story.grid(row=2,column=1,columnspan=2,sticky='w');ttk.Button(top,text='2. Extract Story Loads',command=self.extract).grid(row=2,column=3,padx=4)
        f=ttk.Frame(self,padding=(10,0));f.pack(fill='x');ttk.Label(f,text='RAM Concept template (.cpt):').grid(row=0,column=0);self.cpt=tk.StringVar();ttk.Entry(f,textvariable=self.cpt,width=86).grid(row=0,column=1,padx=5);ttk.Button(f,text='Browse',command=self.browse_cpt).grid(row=0,column=2);ttk.Button(f,text='3. Create RAM CPT Copy',command=self.write_ram).grid(row=0,column=3,padx=5);ttk.Button(f,text='Export CSV',command=self.export_csv).grid(row=0,column=4,padx=5)
        cols=('kind','pattern','object','fx','fy','fz','map','status');self.tree=ttk.Treeview(self,columns=cols,show='headings');widths=[80,130,155,85,85,85,160,350]
        for c,w in zip(cols,widths):self.tree.heading(c,text=c.upper());self.tree.column(c,width=w,anchor='w')
        self.tree.pack(fill='both',expand=True,padx=10,pady=10);self.status=tk.StringVar(value='Select an EDB or E2K file.');ttk.Label(self,textvariable=self.status,relief='sunken',anchor='w').pack(fill='x',side='bottom')
    def browse_source(self):
        types=[('ETABS Database','*.edb'),('All files','*.*')] if self.mode.get()=='EDB' else [('ETABS Text','*.e2k'),('ETABS Text Backup','*.$et'),('All files','*.*')];p=filedialog.askopenfilename(filetypes=types)
        if p:self.source.set(p)
    def read_source(self):
        p=self.source.get()
        if not p:return
        try:
            if self.mode.get()=='EDB':self.bridge.open_edb_direct(p);stories=self.bridge.stories();self.status.set(f'EDB opened through ETABS API. {len(stories)} stories found.')
            else:
                self.e2k=E2KReader(self.cfg).read(p);stories=self.e2k.stories();diag=Path(p).with_suffix('.e2k_diagnostic.json');diag.write_text(json.dumps(self.e2k.diagnostics,indent=2));self.status.set(f'E2K read directly. {len(stories)} stories detected. Diagnostic: {diag.name}')
            self.story['values']=stories
            if stories:self.story.current(0)
        except Exception as e:messagebox.showerror('Read model failed',str(e)+'\n\n'+traceback.format_exc())
    def extract(self):
        st=self.story.get()
        if not st:return
        try:
            self.records=self.bridge.extract_story(st) if self.mode.get()=='EDB' else self.e2k.extract_story(st);self.refresh();ok=sum(r.supported for r in self.records)
            if self.mode.get()=='E2K':Path(self.source.get()).with_suffix('.e2k_diagnostic.json').write_text(json.dumps(self.e2k.diagnostics,indent=2))
            self.status.set(f'{st}: {len(self.records)} loads read; {ok} transferable; {len(self.records)-ok} review.')
        except Exception as e:messagebox.showerror('Extract failed',str(e)+'\n\n'+traceback.format_exc())
    def story_diagnostics(self):
        s=self.story.get()
        if not s:
            messagebox.showwarning("Story","Select a story first."); return
        try:
            if self.mode.get()=="EDB":
                counts=self.bridge.story_object_counts(s)
                report={
                    "story":s,
                    "object_counts":counts,
                    "connection":self.bridge.diagnostics()
                }
                p=Path(self.source.get()).with_name(Path(self.source.get()).stem+"_"+s.replace("/","_")+"_story_diagnostic.json")
                p.write_text(json.dumps(report,indent=2),encoding="utf-8")
                messagebox.showinfo("Story Diagnostics",
                    f"Story: {s}\nAreas: {counts['areas']}\nFrames: {counts['frames']}\nPoints: {counts['points']}\n\nReport:\n{p}")
                self.status.set(f"{s}: {counts['areas']} areas, {counts['frames']} frames, {counts['points']} points.")
            else:
                messagebox.showinfo("Story Diagnostics","E2K diagnostics are generated beside the E2K file.")
        except Exception as e:
            messagebox.showerror("Diagnostics failed",str(e)+"\n\n"+traceback.format_exc())

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.records:
            a,t,_=resolve_mapping(r.load_pattern,self.cfg);status='OK' if r.supported else 'REVIEW: '+r.warning
            if a=='skip':status='SKIP (mapping rule)'
            elif a=='review' and r.supported:status='REVIEW (unmatched load pattern)'
            self.tree.insert('','end',values=(r.kind,r.load_pattern,r.object_name,f'{r.fx:.4g}',f'{r.fy:.4g}',f'{r.fz:.4g}',t,status))
    def browse_cpt(self):
        p=filedialog.askopenfilename(filetypes=[('RAM Concept','*.cpt'),('All files','*.*')])
        if p:self.cpt.set(p)
    def write_ram(self):
        if not self.records:messagebox.showwarning('No loads','Extract loads first.');return
        if not self.cpt.get():self.browse_cpt()
        if not self.cpt.get():return
        src=Path(self.cpt.get());out=filedialog.asksaveasfilename(defaultextension='.cpt',initialfile=src.stem+'_ETABS_LOADS.cpt',initialdir=str(src.parent),filetypes=[('RAM Concept','*.cpt')])
        if not out:return
        try:
            rep=write_copy(src,out,self.records,self.cfg,False);Path(out).with_suffix('.transfer_report.json').write_text(json.dumps(rep,indent=2));messagebox.showinfo('Transfer complete',f"Created:\n{out}\n\nWritten: {rep['written']}\nSkipped: {rep['skipped']}\nReview: {rep['review']}\nUnsupported: {rep['unsupported']}\nDuplicates: {rep['duplicates']}\n\nVerify each RAM loading layer before design.")
        except Exception as e:messagebox.showerror('Write failed',str(e)+'\n\n'+traceback.format_exc())
    def export_csv(self):
        if not self.records:return
        p=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')],initialfile=f'{self.story.get()}_ETABS_loads.csv')
        if not p:return
        fields=['story','kind','object_name','load_pattern','points','fx','fy','fz','mx','my','val2_fx','val2_fy','val2_fz','supported','warning','ram_action','ram_loading_type']
        with open(p,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for r in self.records:
                a,t,_=resolve_mapping(r.load_pattern,self.cfg);d=r.to_dict();d['points']=json.dumps(d['points']);d['ram_action']=a;d['ram_loading_type']=t;w.writerow({k:d.get(k,'') for k in fields})
if __name__=='__main__':App().mainloop()
