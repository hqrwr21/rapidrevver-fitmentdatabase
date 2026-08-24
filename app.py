import streamlit as st
import pandas as pd
import boto3

# --- 1. Connect to Backblaze B2 ---
B2_ENDPOINT = st.secrets["B2_ENDPOINT"]
B2_KEY_ID = st.secrets["B2_KEY_ID"]
B2_APP_KEY = st.secrets["B2_APP_KEY"]
B2_BUCKET = st.secrets["B2_BUCKET"]

# Maximum rows to render in the browser to prevent crashes
MAX_DISPLAY_ROWS = 5000 

@st.cache_resource
def init_b2():
    return boto3.client(
        's3',
        endpoint_url=B2_ENDPOINT,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY
    )

s3_client = init_b2()

st.set_page_config(page_title="PC Fitment Database", layout="wide")

if "fitment_queue" not in st.session_state:
    st.session_state.fitment_queue = []
if "sema_fitment_queue" not in st.session_state:
    st.session_state.sema_fitment_queue = []

# --- 2. Data Engine (Full In-Memory Cache with Grouping) ---
@st.cache_data(ttl=600, show_spinner=False)
def load_all_data():
    """Fetches ALL CSVs from Backblaze B2 and assigns them to PC Fitment or SEMA groups."""
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=B2_BUCKET)
        
        all_dfs = []
        for page in page_iterator:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    if key.lower().endswith('.csv'):
                        obj_data = s3_client.get_object(Bucket=B2_BUCKET, Key=key)
                        df = pd.read_csv(obj_data['Body'], dtype=str)
                        
                        df["SourceFile"] = key.split('/')[-1] 
                        
                        if key.startswith('sema/coast-to-coast/'):
                            df['DataType'] = 'SEMA'
                            df['Brand'] = 'Coast to Coast'
                        elif key.startswith('sema/trailfx/'):
                            df['DataType'] = 'SEMA'
                            df['Brand'] = 'TrailFX'
                        elif key.startswith('pc-fitment/') or key.startswith('aces/'):
                            df['DataType'] = 'PC'
                            df['Brand'] = 'N/A'
                        else:
                            df['DataType'] = 'PC'
                            df['Brand'] = 'N/A'
                            
                        all_dfs.append(df)
                        
        if all_dfs:
            df_combined = pd.concat(all_dfs, ignore_index=True)
            return df_combined.fillna("")
    except Exception as e:
        print(f"Backblaze B2 Fetch Error: {e}")
        
    return pd.DataFrame()

df_main = load_all_data()

def get_dropdown_values(df, column, filters=None):
    if df.empty or column not in df.columns:
        return []
        
    filtered_df = df.copy()
    if filters:
        for f_col, f_val in filters.items():
            if f_val and f_val != "All" and f_col in filtered_df.columns:
                if isinstance(f_val, list):
                    filtered_df = filtered_df[filtered_df[f_col].isin(f_val)]
                else:
                    filtered_df = filtered_df[filtered_df[f_col] == f_val]
                    
    unique_vals = filtered_df[column].dropna().unique().tolist()
    unique_vals = sorted([val for val in unique_vals if val != ""])
    return unique_vals

def get_all_display_cols(df, preferred_order):
    if df.empty:
        return preferred_order
    existing_preferred = [c for c in preferred_order if c in df.columns]
    extra_cols = [c for c in df.columns if c not in preferred_order and c not in ["id", "DataType", "Brand"]]
    return existing_preferred + extra_cols

# --- 3. Global CSV Uploader ---
with st.expander("Import New Data (CSV)"):
    st.write("Upload your CSV data and route it to the correct group.")
    
    col1, col2 = st.columns(2)
    with col1:
        upload_module = st.selectbox("Data Category", ["PC Fitment", "SEMA Data"])
    with col2:
        if upload_module == "SEMA Data":
            sema_brand = st.selectbox("SEMA Brand", ["Coast to Coast", "TrailFX"])
        else:
            st.write("") 
            
    uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"])
    replace_data = st.checkbox("Delete old data in this category before uploading", value=True)
    
    if uploaded_file is not None:
        st.write("File Preview (First 10 rows):")
        df_preview = pd.read_csv(uploaded_file, dtype=str)
        st.dataframe(df_preview.head(10), use_container_width=True)
        uploaded_file.seek(0) 

        if st.button("Upload to Database"):
            with st.spinner("Uploading directly to Backblaze..."):
                try:
                    if upload_module == "PC Fitment":
                        target_prefix = "pc-fitment/"
                    else:
                        brand_folder = "coast-to-coast" if sema_brand == "Coast to Coast" else "trailfx"
                        target_prefix = f"sema/{brand_folder}/"
                        
                    target_key = f"{target_prefix}{uploaded_file.name}"

                    if replace_data:
                        st.info(f"Clearing old files from {target_prefix}...")
                        paginator = s3_client.get_paginator('list_objects_v2')
                        for page in paginator.paginate(Bucket=B2_BUCKET, Prefix=target_prefix):
                            if 'Contents' in page:
                                del_objs = [{'Key': obj['Key']} for obj in page['Contents']]
                                s3_client.delete_objects(Bucket=B2_BUCKET, Delete={'Objects': del_objs})
                    
                    s3_client.upload_fileobj(uploaded_file, B2_BUCKET, target_key)
                    
                    st.success(f"Successfully uploaded {uploaded_file.name} to {target_prefix}")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error during upload: {e}")

st.divider()

# --- 4. App Navigation ---
st.sidebar.title("Navigation")
main_module = st.sidebar.selectbox("Select Database", ["PC Fitment", "SEMA Data"])
st.sidebar.divider()

df_pc = df_main[df_main['DataType'] == 'PC'] if not df_main.empty else pd.DataFrame()
df_sema = df_main[df_main['DataType'] == 'SEMA'] if not df_main.empty else pd.DataFrame()

PC_PREFERRED_COLS = ["SourceFile", "Year", "Make", "Model", "VehicleType", "Region", "BlockType", "BodyType", "BodyNumDoors", "SubModel", "BedLength", "BedTypeName", "WheelBase"]
SEMA_PREFERRED_COLS = ["SourceFile", "Brand", "AAIA_BrandID", "Part", "Year", "Make", "Model", "Submodel", "PartType", "Position", "Quantity", "Region", "FitmentNotes", "MfrLabel", "FuelTypeName", "BedTypeName", "BedLengthInches", "BedLengthMetric"]

# ==========================================
# MODULE: PC FITMENT
# ==========================================
if main_module == "PC Fitment":
    app_mode = st.sidebar.radio("Go to", ["Search Database", "Create PC Template", "View Uploaded Files"])
    display_cols = get_all_display_cols(df_pc, PC_PREFERRED_COLS)

    if app_mode == "Search Database":
        st.title("Auto Parts Fitment Database")
        st.sidebar.header("Search Filters")

        search_car = st.sidebar.text_input("Quick Search Car (e.g., Camry, Civic, F-150)")
        st.sidebar.divider()

        years = ["All"] + get_dropdown_values(df_pc, 'Year')
        makes = ["All"] + get_dropdown_values(df_pc, 'Make')
        
        selected_year = st.sidebar.selectbox("Year", years)
        selected_make = st.sidebar.selectbox("Make", makes)
        
        models = ["All"] + (get_dropdown_values(df_pc, 'Model', filters={'Make': selected_make}) if selected_make != "All" else get_dropdown_values(df_pc, 'Model'))
        selected_model = st.sidebar.selectbox("Model", models)
        
        submodels = ["All"] + (get_dropdown_values(df_pc, 'SubModel', filters={'Make': selected_make, 'Model': selected_model}) if selected_model != "All" else get_dropdown_values(df_pc, 'SubModel'))
        selected_submodel = st.sidebar.selectbox("SubModel", submodels)

        st.sidebar.divider()
        selected_type = st.sidebar.selectbox("Vehicle Type", ["All"] + get_dropdown_values(df_pc, 'VehicleType'))
        selected_region = st.sidebar.selectbox("Region", ["All"] + get_dropdown_values(df_pc, 'Region'))
        selected_blocktype = st.sidebar.selectbox("Block Type", ["All"] + get_dropdown_values(df_pc, 'BlockType'))
        selected_bodytype = st.sidebar.selectbox("Body Type", ["All"] + get_dropdown_values(df_pc, 'BodyType'))
        selected_doors = st.sidebar.selectbox("Num Doors", ["All"] + get_dropdown_values(df_pc, 'BodyNumDoors'))
        selected_bedlength = st.sidebar.selectbox("Bed Length", ["All"] + get_dropdown_values(df_pc, 'BedLength'))
        selected_bedtypename = st.sidebar.selectbox("Bed Type Name", ["All"] + get_dropdown_values(df_pc, 'BedTypeName'))
        selected_wheelbase = st.sidebar.selectbox("Wheel Base", ["All"] + get_dropdown_values(df_pc, 'WheelBase'))

        filtered_df = df_pc.copy()

        if not filtered_df.empty:
            if search_car:
                mask = (filtered_df['Make'].str.contains(search_car, case=False, na=False) | 
                        filtered_df['Model'].str.contains(search_car, case=False, na=False) |
                        filtered_df['SubModel'].str.contains(search_car, case=False, na=False))
                filtered_df = filtered_df[mask]

            if selected_year != "All" and "Year" in filtered_df.columns: filtered_df = filtered_df[filtered_df["Year"] == selected_year]
            if selected_make != "All" and "Make" in filtered_df.columns: filtered_df = filtered_df[filtered_df["Make"] == selected_make]
            if selected_model != "All" and "Model" in filtered_df.columns: filtered_df = filtered_df[filtered_df["Model"] == selected_model]
            if selected_submodel != "All" and "SubModel" in filtered_df.columns: filtered_df = filtered_df[filtered_df["SubModel"] == selected_submodel]
            
            if selected_type != "All" and "VehicleType" in filtered_df.columns: filtered_df = filtered_df[filtered_df["VehicleType"] == selected_type]
            if selected_region != "All" and "Region" in filtered_df.columns: filtered_df = filtered_df[filtered_df["Region"] == selected_region]
            if selected_blocktype != "All" and "BlockType" in filtered_df.columns: filtered_df = filtered_df[filtered_df["BlockType"] == selected_blocktype]
            if selected_bodytype != "All" and "BodyType" in filtered_df.columns: filtered_df = filtered_df[filtered_df["BodyType"] == selected_bodytype]
            if selected_doors != "All" and "BodyNumDoors" in filtered_df.columns: filtered_df = filtered_df[filtered_df["BodyNumDoors"] == selected_doors]
            if selected_bedlength != "All" and "BedLength" in filtered_df.columns: filtered_df = filtered_df[filtered_df["BedLength"] == selected_bedlength]
            if selected_bedtypename != "All" and "BedTypeName" in filtered_df.columns: filtered_df = filtered_df[filtered_df["BedTypeName"] == selected_bedtypename]
            if selected_wheelbase != "All" and "WheelBase" in filtered_df.columns: filtered_df = filtered_df[filtered_df["WheelBase"] == selected_wheelbase]

        st.subheader("Search Results")
        if not filtered_df.empty:
            existing_cols = [c for c in display_cols if c in filtered_df.columns]
            result_to_display = filtered_df[existing_cols]
            
            if len(result_to_display) > MAX_DISPLAY_ROWS:
                st.warning(f"Dataset contains {len(result_to_display)} records. Displaying the first {MAX_DISPLAY_ROWS} rows to prevent browser instability. Please use filters to narrow down the results.")
                st.dataframe(result_to_display.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)
            else:
                st.dataframe(result_to_display, use_container_width=True, hide_index=True)
                st.caption(f"Showing all {len(filtered_df)} matching vehicle records.")
        else:
            st.info("No vehicles found for the selected filters.")

    elif app_mode == "Create PC Template":
        st.title("Multi-Vehicle Fitment Template Builder")
        st.markdown("Build complex fitment lists for listings that cover multiple makes, models, or year ranges.")
        
        pc_part = st.text_input("Part Number for this Listing", placeholder="e.g. 2521-BLK")
        
        st.divider()
        st.subheader("1. Add Vehicle Rules to Listing")
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            builder_makes = st.multiselect("Select Make(s)", get_dropdown_values(df_pc, 'Make'), key="bm_makes")
        with col_m2:
            available_models = get_dropdown_values(df_pc, 'Model', filters={'Make': builder_makes}) if builder_makes else get_dropdown_values(df_pc, 'Model')
            builder_models = st.multiselect("Select Model(s)", available_models, key="bm_models")

        col_y1, col_y2 = st.columns(2)
        with col_y1:
            years_list = get_dropdown_values(df_pc, 'Year')
            builder_year_from = st.selectbox("From Year", ["Any"] + years_list, key="bm_yf")
        with col_y2:
            builder_year_to = st.selectbox("To Year", ["Any"] + years_list, key="bm_yt")

        with st.expander("Optional Filters for this Rule"):
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                avail_submodels = get_dropdown_values(df_pc, 'SubModel', filters={'Make': builder_makes, 'Model': builder_models}) if builder_models else get_dropdown_values(df_pc, 'SubModel')
                builder_submodels = st.multiselect("SubModel(s)", avail_submodels, key="bm_subs")
            with col_s2:
                builder_body = st.multiselect("Body Type(s)", get_dropdown_values(df_pc, 'BodyType'), key="bm_body")
            with col_s3:
                builder_doors = st.multiselect("Num Doors", get_dropdown_values(df_pc, 'BodyNumDoors'), key="bm_doors")
            
            col_s4, col_s5, col_s6, col_s7 = st.columns(4)
            with col_s4:
                builder_bed = st.multiselect("Bed Length(s)", get_dropdown_values(df_pc, 'BedLength'), key="bm_bed")
            with col_s5:
                builder_bedtype = st.multiselect("Bed Type(s)", get_dropdown_values(df_pc, 'BedTypeName'), key="bm_bedtype")
            with col_s6:
                builder_wheelbase = st.multiselect("Wheel Base(s)", get_dropdown_values(df_pc, 'WheelBase'), key="bm_wb")
            with col_s7:
                builder_region = st.multiselect("Region(s)", get_dropdown_values(df_pc, 'Region'), key="bm_reg")

        if st.button("Add Vehicle Rule to Template", type="secondary"):
            if not builder_makes or not builder_models:
                st.warning("Warning: Please select at least one Make and one Model.")
            else:
                new_rule = {
                    "Makes": builder_makes,
                    "Models": builder_models,
                    "YearFrom": builder_year_from,
                    "YearTo": builder_year_to,
                    "SubModels": builder_submodels,
                    "BodyTypes": builder_body,
                    "BodyNumDoors": builder_doors,
                    "BedLengths": builder_bed,
                    "BedTypeNames": builder_bedtype,
                    "WheelBases": builder_wheelbase,
                    "Regions": builder_region
                }
                st.session_state.fitment_queue.append(new_rule)
                st.success(f"Added Rule: {', '.join(builder_makes)} {', '.join(builder_models)} ({builder_year_from}-{builder_year_to})")

        st.divider()
        st.subheader("2. Queued Vehicle Rules for this Listing")
        
        if st.session_state.fitment_queue:
            queue_data = []
            for idx, r in enumerate(st.session_state.fitment_queue, start=1):
                queue_data.append({
                    "Rule #": idx,
                    "Makes": ", ".join(r["Makes"]),
                    "Models": ", ".join(r["Models"]),
                    "Year Range": f"{r['YearFrom']} - {r['YearTo']}",
                    "SubModels": ", ".join(r["SubModels"]) if r["SubModels"] else "All",
                    "Body Types": ", ".join(r["BodyTypes"]) if r["BodyTypes"] else "All",
                    "Doors": ", ".join(r["BodyNumDoors"]) if r["BodyNumDoors"] else "All",
                    "Bed": ", ".join(r["BedLengths"]) if r["BedLengths"] else "All",
                    "Bed Type": ", ".join(r["BedTypeNames"]) if r["BedTypeNames"] else "All",
                    "Wheel Base": ", ".join(r["WheelBases"]) if r["WheelBases"] else "All",
                    "Regions": ", ".join(r["Regions"]) if r["Regions"] else "All"
                })
            st.dataframe(pd.DataFrame(queue_data), use_container_width=True, hide_index=True)
            
            col_q1, col_q2 = st.columns([1, 4])
            with col_q1:
                if st.button("Clear All Rules"):
                    st.session_state.fitment_queue = []
                    st.rerun()
        else:
            st.info("No rules added yet. Use the selector above to add vehicle combinations to your listing.")

        st.divider()
        if st.button("Generate Master Grid", type="primary"):
            if not st.session_state.fitment_queue:
                st.warning("Warning: Please add at least one rule to your template first.")
            elif df_pc.empty:
                st.error("Database is empty. Please upload some CSV files first.")
            else:
                with st.spinner("Combining vehicle data..."):
                    master_dfs = []
                    
                    for rule in st.session_state.fitment_queue:
                        rule_df = df_pc.copy()
                        
                        if "Make" in rule_df.columns: rule_df = rule_df[rule_df["Make"].isin(rule["Makes"])]
                        if "Model" in rule_df.columns: rule_df = rule_df[rule_df["Model"].isin(rule["Models"])]
                        
                        if rule["YearFrom"] != "Any" and "Year" in rule_df.columns: 
                            rule_df = rule_df[rule_df["Year"] >= rule["YearFrom"]]
                        if rule["YearTo"] != "Any" and "Year" in rule_df.columns:   
                            rule_df = rule_df[rule_df["Year"] <= rule["YearTo"]]
                        
                        if rule["SubModels"] and "SubModel" in rule_df.columns:    rule_df = rule_df[rule_df["SubModel"].isin(rule["SubModels"])]
                        if rule["BodyTypes"] and "BodyType" in rule_df.columns:    rule_df = rule_df[rule_df["BodyType"].isin(rule["BodyTypes"])]
                        if rule["BodyNumDoors"] and "BodyNumDoors" in rule_df.columns: rule_df = rule_df[rule_df["BodyNumDoors"].isin(rule["BodyNumDoors"])]
                        if rule["BedLengths"] and "BedLength" in rule_df.columns:   rule_df = rule_df[rule_df["BedLength"].isin(rule["BedLengths"])]
                        if rule["BedTypeNames"] and "BedTypeName" in rule_df.columns: rule_df = rule_df[rule_df["BedTypeName"].isin(rule["BedTypeNames"])]
                        if rule["WheelBases"] and "WheelBase" in rule_df.columns:   rule_df = rule_df[rule_df["WheelBase"].isin(rule["WheelBases"])]
                        if rule["Regions"] and "Region" in rule_df.columns:      rule_df = rule_df[rule_df["Region"].isin(rule["Regions"])]
                        
                        master_dfs.append(rule_df)
                                
                    if master_dfs:
                        df_master = pd.concat(master_dfs, ignore_index=True)
                        
                        export_cols = [c for c in display_cols if c in df_master.columns and c != "SourceFile"]
                        df_master = df_master[export_cols]
                        
                        df_master = df_master.drop_duplicates().sort_values(by=["Make", "Model", "Year"])
                        
                        if pc_part:
                            df_master.insert(0, "PartNumber", pc_part)
                            
                        st.success(f"Generated {len(df_master)} total unique fitment rows across all rules!")
                        
                        if len(df_master) > MAX_DISPLAY_ROWS:
                            st.warning(f"Preview limited to first {MAX_DISPLAY_ROWS} rows. Download the CSV to see all {len(df_master)} rows.")
                            st.dataframe(df_master.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)
                        else:
                            st.dataframe(df_master, use_container_width=True, hide_index=True)
                        
                        csv_data = df_master.to_csv(index=False).encode('utf-8')
                        file_name = f"Fitment_{pc_part if pc_part else 'Listing'}.csv"
                        
                        st.download_button(
                            label="Download Combined CSV for PC Fitment",
                            data=csv_data,
                            file_name=file_name,
                            mime="text/csv"
                        )
                        
                        # --- Group By / Summary Section ---
                        st.divider()
                        st.subheader("Summarize Data (For Copy/Pasting into Listings)")
                        st.write("Select the columns to keep. The app will remove duplicates and automatically group the years into ranges for easy copying.")
                        
                        avail_group_cols = [c for c in export_cols if c not in ["Year", "PartNumber"]]
                        default_group = [c for c in ["Make", "Model", "SubModel"] if c in avail_group_cols]
                        
                        pc_grp = st.multiselect("Group By Columns:", avail_group_cols, default=default_group, key="pc_grp")
                        
                        if pc_grp:
                            try:
                                df_grouped = df_master.groupby(pc_grp).agg(
                                    Min_Year=('Year', 'min'),
                                    Max_Year=('Year', 'max')
                                ).reset_index()
                                
                                df_grouped['Year Range'] = df_grouped.apply(
                                    lambda x: f"{x['Min_Year']}-{x['Max_Year']}" if x['Min_Year'] != x['Max_Year'] else str(x['Min_Year']), 
                                    axis=1
                                )
                                df_grouped = df_grouped.drop(columns=['Min_Year', 'Max_Year'])
                                
                                cols_order = pc_grp + ['Year Range']
                                df_grouped = df_grouped[cols_order]
                                
                                st.dataframe(df_grouped, use_container_width=True, hide_index=True)
                                
                                copy_text = []
                                for _, row in df_grouped.iterrows():
                                    row_vals = [str(row[c]) for c in pc_grp if pd.notna(row[c]) and str(row[c]).strip() != ""]
                                    copy_text.append(f"{row['Year Range']} {' '.join(row_vals)}")
                                    
                                st.text_area("Copy/Paste Friendly Text:", value="\n".join(copy_text), height=150)
                            except Exception as e:
                                st.error(f"Could not group data: {e}")

                    else:
                        st.error("No vehicles found in the database matching the queued rules.")

    elif app_mode == "View Uploaded Files":
        st.title("PC Fitment Database File Manager")
        st.markdown("View all the distinct CSV files currently stored in your PC Fitment bucket.")
        
        uploaded_files = get_dropdown_values(df_pc, 'SourceFile')
        
        if not uploaded_files:
            st.info("Your PC Fitment database is currently empty.")
        else:
            selected_file = st.selectbox("Select a file to view its contents:", uploaded_files)
            
            if selected_file:
                st.subheader(f"Data for: {selected_file}")
                
                df_file = df_pc[df_pc["SourceFile"] == selected_file]
                existing_cols = [c for c in display_cols if c in df_file.columns]
                result_to_display = df_file[existing_cols]
                
                if len(result_to_display) > MAX_DISPLAY_ROWS:
                    st.warning(f"File contains {len(result_to_display)} records. Displaying the first {MAX_DISPLAY_ROWS} rows.")
                    st.dataframe(result_to_display.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)
                else:
                    st.success(f"Loaded all {len(df_file)} rows from {selected_file}.")
                    st.dataframe(result_to_display, use_container_width=True, hide_index=True)


# ==========================================
# MODULE: SEMA DATA
# ==========================================
elif main_module == "SEMA Data":
    app_mode = st.sidebar.radio("Go to", ["Search SEMA Data", "Create SEMA Template", "View SEMA Files"])
    
    display_cols = get_all_display_cols(df_sema, SEMA_PREFERRED_COLS)

    if app_mode == "Search SEMA Data":
        st.title("SEMA Data Explorer")
        st.markdown("Search and filter your Coast to Coast and TrailFX catalogs.")
        
        if df_sema.empty:
            st.info("No SEMA data found. Please use the uploader above to add Coast to Coast or TrailFX files.")
        else:
            st.sidebar.header("SEMA Filters")
            
            search_part = st.sidebar.text_input("Quick Search Part Number")
            st.sidebar.divider()
            
            selected_brand = st.sidebar.selectbox("SEMA Brand", ["All"] + get_dropdown_values(df_sema, 'Brand'))
            
            years = ["All"] + get_dropdown_values(df_sema, 'Year')
            makes = ["All"] + get_dropdown_values(df_sema, 'Make')
            
            selected_year = st.sidebar.selectbox("Year", years)
            selected_make = st.sidebar.selectbox("Make", makes)
            
            models = ["All"] + (get_dropdown_values(df_sema, 'Model', filters={'Make': selected_make}) if selected_make != "All" else get_dropdown_values(df_sema, 'Model'))
            selected_model = st.sidebar.selectbox("Model", models)
            
            submodels = ["All"] + (get_dropdown_values(df_sema, 'Submodel', filters={'Make': selected_make, 'Model': selected_model}) if selected_model != "All" else get_dropdown_values(df_sema, 'Submodel'))
            selected_submodel = st.sidebar.selectbox("Submodel", submodels)
            
            st.sidebar.divider()
            
            part_types = ["All"] + get_dropdown_values(df_sema, 'PartType')
            selected_parttype = st.sidebar.selectbox("Part Type", part_types)
            
            positions = ["All"] + get_dropdown_values(df_sema, 'Position')
            selected_position = st.sidebar.selectbox("Position", positions)
            
            filtered_df = df_sema.copy()
            
            if selected_brand != "All":
                filtered_df = filtered_df[filtered_df["Brand"] == selected_brand]
                
            if search_part and "Part" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Part"].astype(str).str.contains(search_part, case=False, na=False)]
                
            if selected_year != "All" and "Year" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Year"] == selected_year]
            if selected_make != "All" and "Make" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Make"] == selected_make]
            if selected_model != "All" and "Model" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Model"] == selected_model]
            if selected_submodel != "All" and "Submodel" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Submodel"] == selected_submodel]
            if selected_parttype != "All" and "PartType" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["PartType"] == selected_parttype]
            if selected_position != "All" and "Position" in filtered_df.columns:
                filtered_df = filtered_df[filtered_df["Position"] == selected_position]

            st.subheader("SEMA Search Results")
            if not filtered_df.empty:
                existing_cols = [c for c in display_cols if c in filtered_df.columns]
                result_to_display = filtered_df[existing_cols]
                
                if len(result_to_display) > MAX_DISPLAY_ROWS:
                    st.warning(f"Dataset contains {len(result_to_display)} records. Displaying the first {MAX_DISPLAY_ROWS} rows. Please use filters to narrow down the results.")
                    st.dataframe(result_to_display.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)
                else:
                    st.dataframe(result_to_display, use_container_width=True, hide_index=True)
                    st.caption(f"Showing all {len(filtered_df)} matching SEMA records.")
            else:
                st.info("No records found for the selected filters.")

    elif app_mode == "Create SEMA Template":
        st.title("Multi-Vehicle SEMA Template Builder")
        st.markdown("Build complex fitment lists for SEMA listings that cover multiple makes, models, or year ranges.")
        
        sema_part = st.text_input("Part Number for this Listing", placeholder="e.g. TFX-1234")
        
        st.divider()
        st.subheader("1. Add Vehicle Rules to Listing")
        
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            builder_makes = st.multiselect("Select Make(s)", get_dropdown_values(df_sema, 'Make'), key="sm_makes")
        with col_m2:
            available_models = get_dropdown_values(df_sema, 'Model', filters={'Make': builder_makes}) if builder_makes else get_dropdown_values(df_sema, 'Model')
            builder_models = st.multiselect("Select Model(s)", available_models, key="sm_models")

        col_y1, col_y2 = st.columns(2)
        with col_y1:
            years_list = get_dropdown_values(df_sema, 'Year')
            builder_year_from = st.selectbox("From Year", ["Any"] + years_list, key="sm_yf")
        with col_y2:
            builder_year_to = st.selectbox("To Year", ["Any"] + years_list, key="sm_yt")

        with st.expander("Optional Filters for this Rule"):
            col_s1, col_s2, col_s3 = st.columns(3)
            with col_s1:
                builder_brands = st.multiselect("SEMA Brand(s)", get_dropdown_values(df_sema, 'Brand'), key="sm_brand")
            with col_s2:
                avail_submodels = get_dropdown_values(df_sema, 'Submodel', filters={'Make': builder_makes, 'Model': builder_models}) if builder_models else get_dropdown_values(df_sema, 'Submodel')
                builder_submodels = st.multiselect("Submodel(s)", avail_submodels, key="sm_subs")
            with col_s3:
                builder_parttypes = st.multiselect("Part Type(s)", get_dropdown_values(df_sema, 'PartType'), key="sm_ptype")
            
            col_s4, col_s5 = st.columns(2)
            with col_s4:
                builder_positions = st.multiselect("Position(s)", get_dropdown_values(df_sema, 'Position'), key="sm_pos")
            with col_s5:
                builder_regions = st.multiselect("Region(s)", get_dropdown_values(df_sema, 'Region'), key="sm_reg")

        if st.button("Add Vehicle Rule to Template", type="secondary"):
            if not builder_makes or not builder_models:
                st.warning("Warning: Please select at least one Make and one Model.")
            else:
                new_rule = {
                    "Brands": builder_brands,
                    "Makes": builder_makes,
                    "Models": builder_models,
                    "YearFrom": builder_year_from,
                    "YearTo": builder_year_to,
                    "Submodels": builder_submodels,
                    "PartTypes": builder_parttypes,
                    "Positions": builder_positions,
                    "Regions": builder_regions
                }
                st.session_state.sema_fitment_queue.append(new_rule)
                st.success(f"Added Rule: {', '.join(builder_makes)} {', '.join(builder_models)} ({builder_year_from}-{builder_year_to})")

        st.divider()
        st.subheader("2. Queued Vehicle Rules for this Listing")
        
        if st.session_state.sema_fitment_queue:
            queue_data = []
            for idx, r in enumerate(st.session_state.sema_fitment_queue, start=1):
                queue_data.append({
                    "Rule #": idx,
                    "Brands": ", ".join(r["Brands"]) if r["Brands"] else "All",
                    "Makes": ", ".join(r["Makes"]),
                    "Models": ", ".join(r["Models"]),
                    "Year Range": f"{r['YearFrom']} - {r['YearTo']}",
                    "Submodels": ", ".join(r["Submodels"]) if r["Submodels"] else "All",
                    "Part Types": ", ".join(r["PartTypes"]) if r["PartTypes"] else "All",
                    "Positions": ", ".join(r["Positions"]) if r["Positions"] else "All",
                    "Regions": ", ".join(r["Regions"]) if r["Regions"] else "All"
                })
            st.dataframe(pd.DataFrame(queue_data), use_container_width=True, hide_index=True)
            
            col_q1, col_q2 = st.columns([1, 4])
            with col_q1:
                if st.button("Clear All Rules"):
                    st.session_state.sema_fitment_queue = []
                    st.rerun()
        else:
            st.info("No rules added yet. Use the selector above to add vehicle combinations to your listing.")

        st.divider()
        if st.button("Generate Master SEMA Grid", type="primary"):
            if not st.session_state.sema_fitment_queue:
                st.warning("Warning: Please add at least one rule to your template first.")
            elif df_sema.empty:
                st.error("Database is empty. Please upload some CSV files first.")
            else:
                with st.spinner("Combining vehicle data..."):
                    master_dfs = []
                    
                    for rule in st.session_state.sema_fitment_queue:
                        rule_df = df_sema.copy()
                        
                        if rule["Brands"] and "Brand" in rule_df.columns: rule_df = rule_df[rule_df["Brand"].isin(rule["Brands"])]
                        if "Make" in rule_df.columns: rule_df = rule_df[rule_df["Make"].isin(rule["Makes"])]
                        if "Model" in rule_df.columns: rule_df = rule_df[rule_df["Model"].isin(rule["Models"])]
                        
                        if rule["YearFrom"] != "Any" and "Year" in rule_df.columns: 
                            rule_df = rule_df[rule_df["Year"] >= rule["YearFrom"]]
                        if rule["YearTo"] != "Any" and "Year" in rule_df.columns:   
                            rule_df = rule_df[rule_df["Year"] <= rule["YearTo"]]
                        
                        if rule["Submodels"] and "Submodel" in rule_df.columns:    rule_df = rule_df[rule_df["Submodel"].isin(rule["Submodels"])]
                        if rule["PartTypes"] and "PartType" in rule_df.columns:    rule_df = rule_df[rule_df["PartType"].isin(rule["PartTypes"])]
                        if rule["Positions"] and "Position" in rule_df.columns: rule_df = rule_df[rule_df["Position"].isin(rule["Positions"])]
                        if rule["Regions"] and "Region" in rule_df.columns:      rule_df = rule_df[rule_df["Region"].isin(rule["Regions"])]
                        
                        master_dfs.append(rule_df)
                                
                    if master_dfs:
                        df_master = pd.concat(master_dfs, ignore_index=True)
                        
                        export_cols = [c for c in display_cols if c in df_master.columns and c != "SourceFile"]
                        df_master = df_master[export_cols]
                        
                        df_master = df_master.drop_duplicates().sort_values(by=["Brand", "Make", "Model", "Year"])
                        
                        # Apply the global part number override if the user typed one in
                        if sema_part:
                            if "Part" in df_master.columns:
                                df_master["Part"] = sema_part
                            else:
                                df_master.insert(0, "Part", sema_part)
                            
                        st.success(f"Generated {len(df_master)} total unique fitment rows across all rules!")
                        
                        if len(df_master) > MAX_DISPLAY_ROWS:
                            st.warning(f"Preview limited to first {MAX_DISPLAY_ROWS} rows. Download the CSV to see all {len(df_master)} rows.")
                            st.dataframe(df_master.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)
                        else:
                            st.dataframe(df_master, use_container_width=True, hide_index=True)
                        
                        csv_data = df_master.to_csv(index=False).encode('utf-8')
                        file_name = f"SEMA_Fitment_{sema_part if sema_part else 'Listing'}.csv"
                        
                        st.download_button(
                            label="Download Combined SEMA CSV",
                            data=csv_data,
                            file_name=file_name,
                            mime="text/csv"
                        )
                        
                        # --- Group By / Summary Section ---
                        st.divider()
                        st.subheader("Summarize Data (For Copy/Pasting into Listings)")
                        st.write("Select the columns to keep. The app will remove duplicates and automatically group the years into ranges for easy copying.")
                        
                        avail_group_cols = [c for c in export_cols if c not in ["Year", "PartNumber", "Part"]]
                        default_group = [c for c in ["Make", "Model", "Submodel"] if c in avail_group_cols]
                        
                        group_cols = st.multiselect("Group By Columns:", avail_group_cols, default=default_group, key="sema_grp")
                        
                        if group_cols:
                            try:
                                df_grouped = df_master.groupby(group_cols).agg(
                                    Min_Year=('Year', 'min'),
                                    Max_Year=('Year', 'max')
                                ).reset_index()
                                
                                df_grouped['Year Range'] = df_grouped.apply(
                                    lambda x: f"{x['Min_Year']}-{x['Max_Year']}" if x['Min_Year'] != x['Max_Year'] else str(x['Min_Year']), 
                                    axis=1
                                )
                                df_grouped = df_grouped.drop(columns=['Min_Year', 'Max_Year'])
                                
                                cols_order = group_cols + ['Year Range']
                                df_grouped = df_grouped[cols_order]
                                
                                st.dataframe(df_grouped, use_container_width=True, hide_index=True)
                                
                                copy_text = []
                                for _, row in df_grouped.iterrows():
                                    row_vals = [str(row[c]) for c in group_cols if pd.notna(row[c]) and str(row[c]).strip() != ""]
                                    copy_text.append(f"{row['Year Range']} {' '.join(row_vals)}")
                                    
                                st.text_area("Copy/Paste Friendly Text:", value="\n".join(copy_text), height=150)
                            except Exception as e:
                                st.error(f"Could not group data: {e}")

                    else:
                        st.error("No vehicles found in the database matching the queued rules.")

    elif app_mode == "View SEMA Files":
        st.title("SEMA Database File Manager")
        st.markdown("View all the distinct CSV files currently stored in your SEMA bucket.")
        
        uploaded_files = get_dropdown_values(df_sema, 'SourceFile')
        
        if not uploaded_files:
            st.info("Your SEMA database is currently empty.")
        else:
            selected_file = st.selectbox("Select a file to view its contents:", uploaded_files)
            
            if selected_file:
                st.subheader(f"Data for: {selected_file}")
                
                df_file = df_sema[df_sema["SourceFile"] == selected_file]
                existing_cols = [c for c in display_cols if c in df_file.columns]
                result_to_display = df_file[existing_cols]
                
                if len(result_to_display) > MAX_DISPLAY_ROWS:
                    st.warning(f"File contains {len(result_to_display)} records. Displaying the first {MAX_DISPLAY_ROWS} rows.")
                    st.dataframe(result_to_display.head(MAX_DISPLAY_ROWS), use_container_width=True, hide_index=True)
                else:
                    st.success(f"Loaded all {len(df_file)} rows from {selected_file}.")
                    st.dataframe(result_to_display, use_container_width=True, hide_index=True)